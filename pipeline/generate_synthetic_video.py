"""
Generador de video sintético para pruebas del pipeline.

Simula "personas" (círculos de colores) moviéndose por pasillos de una
tienda ficticia, incluyendo:
- Personas que pasan de largo (cruzan sin detenerse)
- Personas que se detienen frente a una "góndola" (dwell time)
- Movimiento aleatorio con velocidad variable

Esto NO reemplaza el dataset real (MERL) ni el video del comercio real,
es solo para validar que el pipeline de tracking funciona end-to-end
mientras se consiguen/preparan los datos reales.
"""

import cv2
import numpy as np
import random

# --- Configuración del video ---
WIDTH, HEIGHT = 960, 540
FPS = 24
DURATION_SECONDS = 30
N_FRAMES = FPS * DURATION_SECONDS
OUTPUT_PATH = "data/raw/synthetic_store_demo.webm"

# --- "Góndolas" ficticias (rectángulos) para dar contexto visual ---
GONDOLAS = [
    {"name": "Gondola_A", "rect": (100, 80, 300, 160)},   # x1,y1,x2,y2
    {"name": "Gondola_B", "rect": (400, 80, 600, 160)},
    {"name": "Gondola_C", "rect": (700, 80, 900, 160)},
    {"name": "Gondola_D", "rect": (100, 380, 300, 460)},
    {"name": "Gondola_E", "rect": (700, 380, 900, 460)},
]


class SyntheticPerson:
    """Simula una persona caminando por la tienda con posible parada (dwell)."""

    def __init__(self, person_id):
        self.id = person_id
        self.x = random.uniform(0, WIDTH)
        self.y = random.uniform(200, 350)  # entra por el "pasillo central"
        self.color = tuple(int(c) for c in np.random.randint(80, 255, 3))
        self.radius = 14
        self.target_gondola = random.choice(GONDOLAS)
        self.state = "walking"  # walking | approaching | dwelling | leaving
        self.dwell_frames_left = 0
        self.speed = random.uniform(2.0, 4.5)
        self.vx = random.choice([-1, 1]) * self.speed
        self.vy = random.uniform(-0.5, 0.5)
        self.will_stop = random.random() < 0.55  # ~55% se detiene en una góndola

    def _gondola_center(self, gondola):
        x1, y1, x2, y2 = gondola["rect"]
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    def step(self):
        if self.state == "walking":
            self.x += self.vx
            self.y += self.vy
            if self.will_stop:
                gx, gy = self._gondola_center(self.target_gondola)
                dist = np.hypot(self.x - gx, self.y - gy)
                if dist < 220 and random.random() < 0.02:
                    self.state = "approaching"
        elif self.state == "approaching":
            gx, gy = self._gondola_center(self.target_gondola)
            dx, dy = gx - self.x, gy - self.y
            dist = np.hypot(dx, dy)
            if dist < 40:
                self.state = "dwelling"
                self.dwell_frames_left = random.randint(int(FPS * 1.5), int(FPS * 5))
            else:
                self.x += dx / dist * 2.5
                self.y += dy / dist * 2.5
        elif self.state == "dwelling":
            self.dwell_frames_left -= 1
            self.x += random.uniform(-0.3, 0.3)
            self.y += random.uniform(-0.3, 0.3)
            if self.dwell_frames_left <= 0:
                self.state = "leaving"
                self.vx = random.choice([-1, 1]) * self.speed
                self.vy = random.uniform(-0.5, 0.5)
        elif self.state == "leaving":
            self.x += self.vx
            self.y += self.vy

        # Rebote en bordes verticales del "pasillo"
        if self.y < 180 or self.y > 420:
            self.vy *= -1

    def is_out_of_bounds(self):
        return self.x < -30 or self.x > WIDTH + 30

    def draw(self, frame):
        color = self.color
        if self.state == "dwelling":
            color = (0, 0, 255)  # rojo mientras "interactúa" con la góndola
        cv2.circle(frame, (int(self.x), int(self.y)), self.radius, color, -1)
        cv2.putText(frame, f"P{self.id}", (int(self.x) - 10, int(self.y) - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)


def draw_static_scene(frame):
    """Dibuja las góndolas y el layout base de la tienda ficticia."""
    overlay = frame.copy()
    for g in GONDOLAS:
        x1, y1, x2, y2 = g["rect"]
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (90, 90, 90), -1)
        cv2.putText(overlay, g["name"], (x1 + 5, y1 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, "TIENDA SINTETICA - DEMO PIPELINE", (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)


def main():
    # VP8/WebM, no mp4v -- mp4v genera un .mp4 que la mayoría de
    # navegadores no reproducen (ver docs/architecture.md sección 19).
    # Este video sintético es una herramienta de desarrollo, pero data/raw/
    # es exactamente donde vive cualquier video de cámara real, y nada
    # impide subir/referenciar este archivo como el de una cámara -- si
    # eso pasara, terminaría mostrándose en el mismo <video> del asistente
    # de configuración que mostró el bug original (ver
    # dashboard/video_utils.py:trim_video()).
    fourcc = cv2.VideoWriter_fourcc(*"VP80")
    writer = cv2.VideoWriter(OUTPUT_PATH, fourcc, FPS, (WIDTH, HEIGHT))

    people = [SyntheticPerson(i) for i in range(6)]
    next_id = len(people)
    spawn_cooldown = 0

    for frame_idx in range(N_FRAMES):
        frame = np.full((HEIGHT, WIDTH, 3), (40, 40, 40), dtype=np.uint8)
        draw_static_scene(frame)

        # Actualizar y dibujar personas
        for p in people:
            p.step()
            p.draw(frame)

        # Eliminar quienes salieron del frame
        people = [p for p in people if not p.is_out_of_bounds()]

        # Generar nuevas personas ocasionalmente
        spawn_cooldown -= 1
        if spawn_cooldown <= 0 and len(people) < 10:
            people.append(SyntheticPerson(next_id))
            next_id += 1
            spawn_cooldown = random.randint(int(FPS * 0.5), int(FPS * 2))

        writer.write(frame)

    writer.release()
    print(f"Video sintético generado en: {OUTPUT_PATH}")
    print(f"Duración: {DURATION_SECONDS}s, {N_FRAMES} frames, {FPS} FPS, {WIDTH}x{HEIGHT}")


if __name__ == "__main__":
    main()