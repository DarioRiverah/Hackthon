"""
Validación cruzada contra el dataset smart-store-znibq (Roboflow).

Corre nuestro propio modelo YA ENTRENADO (YOLO26-pose, el mismo que usa
pipeline/detect_and_track.py para cuerpo Y mano en una sola pasada)
sobre las imágenes de este dataset, y compara contra sus anotaciones de
verdad (ground truth) para medir con números reales -- no solo
impresión visual -- qué tan bien generaliza a una vista lateral/de
esquina, distinta a la vista cenital de MERL con la que validamos todo
el resto del proyecto.

Esto es una prueba de UNA SOLA IMAGEN a la vez (sin tracking, ya que
este dataset son imágenes sueltas, no video) -- valida la calidad de
detección por frame, no la calidad de seguimiento entre frames.

Dos validaciones independientes:

    1. Detección de personas: ¿nuestro detector de personas (COCO,
       clase "person") encuentra las mismas personas que anotó
       smart-store-znibq (su clase "Person")? Se reporta precisión,
       recall y F1 usando IoU >= 0.5 como criterio de acierto.

    2. Detección de mano/interacción: ¿la muñeca que detecta nuestro
       modelo de pose cae dentro de alguna de las cajas que
       smart-store-znibq anotó como interacción de mano
       (Hand-On-Shelf, Hand-With-Product, Hand-In-Cart,
       Arm-With-Product)? Esto NO es una métrica de precisión/recall
       estricta (points-in-box, no box-vs-box), sino una validación de
       plausibilidad: ¿nuestro enfoque de "muñeca entra a zona" tiene
       sentido frente a dónde anotaron humanos que ocurre la
       interacción?

Uso:
    python pipeline\\validate_smart_store.py --dataset-dir data\\raw\\smart_store_znibq --split test
"""

import argparse
import os

import cv2
import yaml
from ultralytics import YOLO

POSE_MODEL_NAME = "yolo26n-pose.pt"
KEYPOINT_LEFT_WRIST = 9
KEYPOINT_RIGHT_WRIST = 10

HAND_INTERACTION_CLASSES = {"Hand-On-Shelf", "Hand-With-Product", "Hand-In-Cart", "Arm-With-Product"}


def parse_args():
    parser = argparse.ArgumentParser(description="Valida nuestros modelos contra smart-store-znibq.")
    parser.add_argument("--dataset-dir", type=str, required=True,
                         help="Carpeta raíz del dataset descomprimido (contiene data.yaml)")
    parser.add_argument("--split", type=str, default="test", choices=["train", "valid", "test"],
                         help="Qué partición usar (default: test, la más honesta para validar)")
    parser.add_argument("--conf", type=float, default=0.2, help="Umbral de confianza (default: 0.2)")
    parser.add_argument("--iou-threshold", type=float, default=0.5,
                         help="IoU mínimo para considerar que una detección acierta (default: 0.5)")
    parser.add_argument("--max-images", type=int, default=None,
                         help="Límite de imágenes a procesar (default: todas)")
    return parser.parse_args()


def load_class_names(dataset_dir):
    with open(os.path.join(dataset_dir, "data.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config["names"]


def parse_yolo_label(label_path, img_w, img_h):
    """Lee un archivo de anotación YOLO (class_id cx cy w h, normalizado)
    y devuelve una lista de (class_id, x1, y1, x2, y2) en píxeles."""
    boxes = []
    if not os.path.exists(label_path):
        return boxes
    with open(label_path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            class_id, cx, cy, w, h = parts
            class_id = int(class_id)
            cx, cy, w, h = float(cx) * img_w, float(cy) * img_h, float(w) * img_w, float(h) * img_h
            x1, y1 = cx - w / 2, cy - h / 2
            x2, y2 = cx + w / 2, cy + h / 2
            boxes.append((class_id, x1, y1, x2, y2))
    return boxes


def compute_iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union = areaA + areaB - inter
    return inter / union if union > 0 else 0


def match_boxes(gt_boxes, pred_boxes, iou_thresh):
    matched_pred = set()
    tp = 0
    for gt in gt_boxes:
        best_iou, best_j = 0, None
        for j, pred in enumerate(pred_boxes):
            if j in matched_pred:
                continue
            iou = compute_iou(gt, pred)
            if iou > best_iou:
                best_iou, best_j = iou, j
        if best_iou >= iou_thresh:
            matched_pred.add(best_j)
            tp += 1
    fn = len(gt_boxes) - tp
    fp = len(pred_boxes) - len(matched_pred)
    return tp, fp, fn


def point_in_box(x, y, box):
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def main():
    args = parse_args()

    class_names = load_class_names(args.dataset_dir)
    person_class_id = class_names.index("Person")
    hand_class_ids = {class_names.index(name) for name in HAND_INTERACTION_CLASSES if name in class_names}

    images_dir = os.path.join(args.dataset_dir, args.split, "images")
    labels_dir = os.path.join(args.dataset_dir, args.split, "labels")

    if not os.path.exists(images_dir):
        print(f"ERROR: no se encontró '{images_dir}'")
        return

    image_files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))])
    if args.max_images:
        image_files = image_files[:args.max_images]

    print(f"Validando contra {len(image_files)} imágenes de '{args.split}'...")

    model = YOLO(POSE_MODEL_NAME)

    total_tp, total_fp, total_fn = 0, 0, 0
    hand_boxes_total = 0
    hand_boxes_hit = 0

    for filename in image_files:
        image_path = os.path.join(images_dir, filename)
        label_path = os.path.join(labels_dir, os.path.splitext(filename)[0] + ".txt")

        img = cv2.imread(image_path)
        if img is None:
            continue
        h, w = img.shape[:2]

        gt_all = parse_yolo_label(label_path, w, h)
        gt_person_boxes = [(x1, y1, x2, y2) for cid, x1, y1, x2, y2 in gt_all if cid == person_class_id]
        gt_hand_boxes = [(x1, y1, x2, y2) for cid, x1, y1, x2, y2 in gt_all if cid in hand_class_ids]

        # Una sola pasada de YOLO26-pose entrega tanto la caja de persona
        # completa (validación 1) como los keypoints de muñeca (validación 2).
        result = model.predict(img, classes=[0], conf=args.conf, verbose=False)[0]

        # --- Validación 1: detección de personas ---
        pred_person_boxes = [tuple(box) for box in result.boxes.xyxy.cpu().numpy()] if result.boxes is not None else []

        tp, fp, fn = match_boxes(gt_person_boxes, pred_person_boxes, args.iou_threshold)
        total_tp += tp
        total_fp += fp
        total_fn += fn

        # --- Validación 2: plausibilidad de mano/interacción ---
        if gt_hand_boxes:
            wrist_points = []
            if result.keypoints is not None:
                kpts_xy = result.keypoints.xy.cpu().numpy()
                kpts_conf = result.keypoints.conf.cpu().numpy() if result.keypoints.conf is not None else None
                for i in range(len(kpts_xy)):
                    for kp_idx in (KEYPOINT_LEFT_WRIST, KEYPOINT_RIGHT_WRIST):
                        x, y = kpts_xy[i][kp_idx]
                        conf = kpts_conf[i][kp_idx] if kpts_conf is not None else 1.0
                        if conf >= 0.3 and (x > 0 or y > 0):
                            wrist_points.append((x, y))

            for hand_box in gt_hand_boxes:
                hand_boxes_total += 1
                if any(point_in_box(x, y, hand_box) for x, y in wrist_points):
                    hand_boxes_hit += 1

    print("\n" + "=" * 60)
    print("VALIDACIÓN 1: Detección de personas (vs. anotación 'Person')")
    print("=" * 60)
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    print(f"TP={total_tp}  FP={total_fp}  FN={total_fn}")
    print(f"Precisión: {precision:.2%}   Recall: {recall:.2%}   F1: {f1:.2%}")

    print("\n" + "=" * 60)
    print("VALIDACIÓN 2: Plausibilidad de detección de mano/interacción")
    print("=" * 60)
    if hand_boxes_total > 0:
        hit_rate = hand_boxes_hit / hand_boxes_total
        print(f"Cajas de interacción anotadas: {hand_boxes_total}")
        print(f"Cajas donde nuestra muñeca detectada cayó dentro: {hand_boxes_hit} ({hit_rate:.1%})")
    else:
        print("No se encontraron cajas de interacción de mano en este split.")

    print("\nNota: la validación 2 no es precisión/recall estricta -- es una")
    print("prueba de plausibilidad (punto-dentro-de-caja), útil para saber si")
    print("nuestro enfoque de 'muñeca entra a zona' tiene sentido frente a")
    print("dónde anotaron humanos que ocurre la interacción real.")


if __name__ == "__main__":
    main()