"""Ventana principal y pantallas (CustomTkinter).

Reglas de este módulo:
* Solo dibuja y reenvía acciones al VotingController; no importa hardware ni red.
* Todo acceso a widgets ocurre en el hilo principal: el controlador se consulta
  con after() (`_tick` -> `controller.pump()`) y avisa por `on_change`.
* Nunca se muestra información biométrica ni la referencia del votante.
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Optional

import customtkinter as ctk

from kiosk_ui.core.controller import UNCERTAIN_MESSAGE, VotingController
from kiosk_ui.core.models import Candidate, Phase, Step, StepStatus, SubmitOutcome
from kiosk_ui.core.ports import DemoHooks
from kiosk_ui.ui import photos
from kiosk_ui.ui.theme import C, Theme

RESULT_AUTO_RETURN_S = 10   # solo tras un registro confirmado
INACTIVE_PHASES = (Phase.AUTH, Phase.VERIFIED, Phase.SELECTING, Phase.REVIEW)

PHASE_SCREEN = {
    Phase.IDLE: "welcome", Phase.AUTH: "auth", Phase.VERIFIED: "verified", Phase.LOADING: "loading",
    Phase.SELECTING: "selection", Phase.REVIEW: "review", Phase.SUBMITTING: "review",
    Phase.RESULT: "result", Phase.ERROR: "result",
}
STAGE_TEXT = {
    Phase.IDLE: "Inicio",
    Phase.AUTH: "Paso 1 de 4 · Identificación", Phase.VERIFIED: "Paso 1 de 4 · Identificación",
    Phase.LOADING: "Paso 1 de 4 · Identificación",
    Phase.SELECTING: "Paso 2 de 4 · Selección",
    Phase.REVIEW: "Paso 3 de 4 · Revisión y envío", Phase.SUBMITTING: "Paso 3 de 4 · Revisión y envío",
    Phase.RESULT: "Paso 4 de 4 · Resultado", Phase.ERROR: "Resultado",
}
STEP_NAMES = {Step.CARD: "Tarjeta", Step.FINGERPRINT: "Huella dactilar", Step.FACE: "Reconocimiento facial"}
STEP_HINTS = {
    Step.CARD: "Validando su tarjeta…",
    Step.FINGERPRINT: "Coloque el dedo sobre el sensor y manténgalo quieto.",
    Step.FACE: "Mire de frente a la cámara y permanezca quieto.",
}
SPINNER = "◐◓◑◒"


# --------------------------------------------------------------- utilidades
class ConfirmGuard:
    """Pide una segunda pulsación (4 s) antes de abandonar la sesión."""

    def __init__(self) -> None:
        self._btn: Optional[ctk.CTkButton] = None
        self._job = None
        self._idle_text = ""

    def press(self, btn: ctk.CTkButton, idle_text: str, armed_text: str, action) -> None:
        if self._job is not None:
            self.disarm()
            action()
            return
        self._btn, self._idle_text = btn, idle_text
        btn.configure(text=armed_text, fg_color=C.ERR, hover_color=C.ERR_HOVER,
                      text_color="white", border_color=C.ERR)
        self._job = btn.after(4000, self.disarm)

    def disarm(self) -> None:
        if self._job is None or self._btn is None:
            return
        try:
            self._btn.after_cancel(self._job)
            self._btn.configure(text=self._idle_text, fg_color=C.SURFACE, hover_color=C.HOVER_LIGHT,
                                text_color=C.NAVY, border_color=C.NAVY)
        except tk.TclError:   # el botón ya no existe
            pass
        self._job = None


class CardIcon(tk.Canvas):
    """Icono de tarjeta acercándose a un lector, dibujado con Canvas."""

    def __init__(self, master, t: Theme) -> None:
        w, h = t.s(320), t.s(210)
        super().__init__(master, width=w, height=h, bg=C.BG, highlightthickness=0)
        lw = t.s(6)
        self._round_rect(lw, h * 0.28, w * 0.74, h - lw, t.s(26), fill=C.SURFACE, outline=C.NAVY, width=lw)
        self._round_rect(w * 0.10, h * 0.47, w * 0.26, h * 0.67, t.s(8), fill=C.BLUE, outline=C.BLUE)
        self.create_line(w * 0.10, h * 0.80, w * 0.60, h * 0.80, fill=C.BORDER, width=lw)
        cx, cy = w * 0.80, h * 0.50
        for r in (0.10, 0.17, 0.24):
            rr = w * r
            self.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=-50, extent=100,
                            style="arc", outline=C.BLUE, width=lw)

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(pts, smooth=True, **kw)


class Screen(ctk.CTkFrame):
    def __init__(self, master, app: "KioskApp") -> None:
        super().__init__(master, fg_color=C.BG, corner_radius=0)
        self.app = app
        self.c: VotingController = app.controller
        self.t: Theme = app.theme

    def on_show(self) -> None: ...
    def on_hide(self) -> None: ...
    def refresh(self) -> None: ...
    def tick(self) -> None: ...

    def label(self, parent, text: str, px: int, bold: bool = False, color: str = C.TEXT, **kw):
        return ctk.CTkLabel(parent, text=text, font=self.t.font(px, bold), text_color=color, **kw)


# ----------------------------------------------------------------- bienvenida
class WelcomeScreen(Screen):
    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.place(relx=0.5, rely=0.45, anchor="center")
        CardIcon(box, t).pack(pady=(0, t.s(24)))
        self.label(box, "Bienvenido", 64, True, C.NAVY).pack()
        self.label(box, "Acerque su tarjeta al lector para comenzar", 34).pack(pady=(t.s(12), 0))
        self.label(box, "Manténgala cerca del lector hasta que cambie la pantalla.", 26,
                   color=C.MUTED).pack(pady=(t.s(8), 0))
        if app.demo is not None:
            self._build_demo(app.demo)

    def _build_demo(self, demo: DemoHooks) -> None:
        t = self.t
        panel = ctk.CTkFrame(self, fg_color="#FFF8E1", border_width=2, border_color="#E0B84C",
                             corner_radius=t.s(16))
        panel.place(relx=0.5, rely=1.0, anchor="s", y=-t.s(24))
        self.label(panel, "Panel de demostración · adaptadores simulados", 22, True,
                   "#5C4300").pack(padx=t.s(24), pady=(t.s(14), t.s(6)))
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(padx=t.s(24), pady=(0, t.s(16)))
        self._menu = ctk.CTkOptionMenu(
            row, values=list(demo.scenario_labels), width=t.s(640), height=t.s(56),
            font=t.font(22), dropdown_font=t.font(22), fg_color=C.NAVY, button_color=C.BLUE,
            button_hover_color=C.NAVY_HOVER, text_color="white")
        self._menu.pack(side="left", padx=(0, t.s(16)))
        t.button(row, "Simular tarjeta", lambda: demo.tap(self._menu.get()),
                 compact=True, width=t.s(280)).pack(side="left")


# ------------------------------------------------------- verificación (auth)
class AuthScreen(Screen):
    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.place(relx=0.5, rely=0.46, anchor="center")
        self.label(box, "Verificando su identidad", 48, True, C.NAVY).pack()
        self.label(box, "Tarjeta, huella y rostro", 28, color=C.MUTED).pack(pady=(t.s(6), t.s(24)))
        self._rows: dict[Step, tuple] = {}
        for step in Step:
            frame = ctk.CTkFrame(box, fg_color=C.SURFACE, corner_radius=t.s(18),
                                 border_width=t.s(3), border_color=C.BORDER)
            frame.pack(fill="x", pady=t.s(8))
            glyph = self.label(frame, "○", 44, True, C.MUTED, width=t.s(70))
            glyph.pack(side="left", padx=(t.s(24), t.s(8)), pady=t.s(14))
            self.label(frame, STEP_NAMES[step], 32, True, anchor="w",
                       width=t.s(460)).pack(side="left")
            status = self.label(frame, "En espera", 28, True, C.MUTED, anchor="e", width=t.s(240))
            status.pack(side="right", padx=t.s(28))
            self._rows[step] = (frame, glyph, status)
        self._msg = self.label(box, "", 28, wraplength=t.s(1000), justify="center")
        self._msg.pack(pady=t.s(20))
        nav = ctk.CTkFrame(box, fg_color="transparent")
        nav.pack()
        self._cancel = t.button(nav, "Cancelar", self.c.reset, "secondary", width=t.s(300))
        self._cancel.grid(row=0, column=0, padx=t.s(12))
        self._retry = t.button(nav, "Reintentar", self.c.retry_step, width=t.s(300))
        self._retry.grid(row=0, column=1, padx=t.s(12))
        self._spin = 0

    def refresh(self) -> None:
        c = self.c
        look = {
            StepStatus.PENDING: ("○", C.MUTED, "En espera"),
            StepStatus.ACTIVE: (SPINNER[self._spin], C.BLUE, "Verificando…"),
            StepStatus.OK: ("✓", C.OK, "Verificado"),
            StepStatus.FAILED: ("✕", C.ERR, "No verificado"),
        }
        for step, (frame, glyph, status) in self._rows.items():
            st = c.steps[step]
            g, color, text = look[st]
            glyph.configure(text=g, text_color=color)
            status.configure(text=text, text_color=color)
            frame.configure(border_color=color if st in (StepStatus.ACTIVE, StepStatus.FAILED) else C.BORDER)
        if c.failed_step is not None:
            self._msg.configure(text=c.step_message, text_color=C.ERR)
            self._retry.configure(text="Intentar de nuevo" if c.failed_step is Step.CARD else "Reintentar")
            self._retry.grid()
        else:
            active = next((s for s in Step if c.steps[s] is StepStatus.ACTIVE), None)
            self._msg.configure(text=STEP_HINTS.get(active, ""), text_color=C.TEXT)
            self._retry.grid_remove()

    def tick(self) -> None:
        idx = int(time.monotonic() * 4) % 4
        if idx == self._spin:
            return
        self._spin = idx
        for step, (_, glyph, _s) in self._rows.items():
            if self.c.steps[step] is StepStatus.ACTIVE:
                glyph.configure(text=SPINNER[idx])


# ------------------------------------------------------ identidad verificada
class VerifiedScreen(Screen):
    """Confirmación neutra: nunca muestra nombre, UID ni datos biométricos."""

    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.place(relx=0.5, rely=0.46, anchor="center")
        self.label(box, "✓", 110, True, C.OK).pack()
        self.label(box, "Identidad verificada correctamente", 48, True, C.NAVY).pack()
        self.label(box, "Ya puede consultar su boleta.", 28, color=C.MUTED).pack(pady=(t.s(12), 0))
        t.button(box, "Continuar", self.c.continue_to_ballot, width=t.s(420), big=True).pack(
            pady=(t.s(32), 0)
        )


# ------------------------------------------------------------------- carga
class LoadingScreen(Screen):
    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.place(relx=0.5, rely=0.46, anchor="center")
        self.label(box, "Preparando su boleta…", 48, True, C.NAVY).pack(pady=(0, t.s(28)))
        self._bar = ctk.CTkProgressBar(box, mode="indeterminate", width=t.s(640), height=t.s(18),
                                       progress_color=C.BLUE, fg_color=C.BORDER)
        self._bar.pack()

    def on_show(self) -> None:
        self._bar.start()

    def on_hide(self) -> None:
        self._bar.stop()


# --------------------------------------------------------------- selección
class CandidateCard(ctk.CTkFrame):
    def __init__(self, master, t: Theme, candidate: Candidate, role: str, on_pick) -> None:
        super().__init__(master, fg_color=C.SURFACE, corner_radius=t.s(22),
                         border_width=t.s(3), border_color=C.BORDER)
        self._t, self._cand, self._on_pick = t, candidate, on_pick
        self._img = photos.candidate_image(candidate, t.s(190))
        wrap = t.s(260)
        self._lbl_photo = ctk.CTkLabel(self, text="", image=self._img)
        self._lbl_name = ctk.CTkLabel(self, text=candidate.name, font=t.font(30, True),
                                      text_color=C.NAVY, wraplength=wrap, justify="center")
        self._lbl_role = ctk.CTkLabel(self, text=role, font=t.font(24), text_color=C.MUTED,
                                      wraplength=wrap, justify="center")
        self._lbl_tag = ctk.CTkLabel(self, text="Toque para elegir", font=t.font(24, True),
                                     text_color=C.BLUE)
        self._lbl_photo.pack(padx=t.s(22), pady=(t.s(22), t.s(8)))
        self._lbl_name.pack(padx=t.s(12))
        self._lbl_role.pack(padx=t.s(12), pady=(t.s(2), t.s(6)))
        self._lbl_tag.pack(pady=(0, t.s(18)))
        for w in (self, self._lbl_photo, self._lbl_name, self._lbl_role, self._lbl_tag):
            w.bind("<Button-1>", self._pressed)

    def _pressed(self, _event=None) -> None:
        self._on_pick(self._cand)

    def set_selected(self, selected: bool) -> None:
        t = self._t
        self.configure(border_color=C.NAVY if selected else C.BORDER,
                       border_width=t.s(8) if selected else t.s(3),
                       fg_color=C.SELECTED_BG if selected else C.SURFACE)
        self._lbl_tag.configure(text="✓ Seleccionado" if selected else "Toque para elegir",
                                text_color=C.NAVY if selected else C.BLUE)


class SelectionScreen(Screen):
    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, pady=(t.s(24), 0))
        self._progress = self.label(head, "", 26, color=C.MUTED)
        self._progress.pack()
        self._title = self.label(head, "", 52, True, C.NAVY)
        self._title.pack()
        self._hint = self.label(head, "", 28)
        self._hint.pack(pady=(t.s(4), 0))
        self._cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._cards_frame.grid(row=1, column=0)
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=2, column=0, pady=(0, t.s(24)))
        self._left = t.button(nav, "Cancelar", self._on_left, "secondary", width=t.s(360))
        self._left.grid(row=0, column=0, padx=t.s(14))
        self._right = t.button(nav, "Siguiente cargo", self.c.next_position, width=t.s(460))
        self._right.grid(row=0, column=1, padx=t.s(14))
        self._guard = ConfirmGuard()
        self._cards: dict[str, CandidateCard] = {}
        self._built: Optional[str] = None

    def on_show(self) -> None:
        self._built = None

    def _left_text(self) -> str:
        c = self.c
        return "Anterior" if c.position_index > 0 and not c.editing_from_review else "Cancelar"

    def _on_left(self) -> None:
        c = self.c
        if self._left_text() == "Anterior":
            self._guard.disarm()
            c.back()
        else:
            self._guard.press(self._left, "Cancelar", "Toque de nuevo para cancelar", c.reset)

    def _pick(self, cand: Candidate) -> None:
        self.c.select(cand.position_id, cand.id)

    def _rebuild(self) -> None:
        pos, t = self.c.current_position, self.t
        for w in self._cards_frame.winfo_children():
            w.destroy()
        self._cards.clear()
        card_w = t.s(300) + 2 * t.s(14)
        avail = self.winfo_toplevel().winfo_width()
        if avail < 200:
            avail = self.winfo_screenwidth()
        cols = max(1, min(len(pos.candidates), avail // card_w))
        for i, cand in enumerate(pos.candidates):
            card = CandidateCard(self._cards_frame, t, cand, pos.title, self._pick)
            card.grid(row=i // cols, column=i % cols, padx=t.s(14), pady=t.s(14), sticky="nsew")
            self._cards[cand.id] = card
        for col in range(cols):
            self._cards_frame.grid_columnconfigure(col, weight=1, uniform="cards")
        self._built = pos.id

    def refresh(self) -> None:
        c, pos = self.c, self.c.current_position
        if pos is None:
            return
        self._guard.disarm()
        if self._built != pos.id:
            self._rebuild()
        self._progress.configure(text=f"Cargo {c.position_index + 1} de {len(c.ballot)}")
        self._title.configure(text=pos.title)
        chosen = c.selections.get(pos.id)
        self._hint.configure(text="Puede cambiar su elección tocando otra tarjeta." if chosen
                             else "Toque la tarjeta del candidato de su elección.")
        for cid, card in self._cards.items():
            card.set_selected(cid == chosen)
        self._left.configure(text=self._left_text())
        last = c.position_index == len(c.ballot) - 1
        self._right.configure(text="Volver a la revisión" if c.editing_from_review
                              else ("Revisar mi selección" if last else "Siguiente cargo"))
        self.t.set_enabled(self._right, c.can_continue)


# ---------------------------------------------------------------- revisión
class ReviewScreen(Screen):
    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, pady=(t.s(24), 0))
        self.label(head, "Revise su selección", 52, True, C.NAVY).pack()
        self.label(head, "Su voto aún no se ha enviado. Se enviará solo al pulsar ENVIAR VOTO.",
                   28).pack(pady=(t.s(4), 0))
        self._rows = ctk.CTkFrame(self, fg_color="transparent")
        self._rows.grid(row=1, column=0)
        self._status = ctk.CTkFrame(self, fg_color="transparent")
        self._status.grid(row=2, column=0, pady=(0, t.s(8)))
        self.label(self._status, "Enviando su voto. Espere la confirmación; no toque la pantalla.",
                   28, True, C.BLUE).pack()
        self._bar = ctk.CTkProgressBar(self._status, mode="indeterminate", width=t.s(640),
                                       height=t.s(14), progress_color=C.BLUE, fg_color=C.BORDER)
        self._bar.pack(pady=(t.s(10), 0))
        self._status.grid_remove()
        self._bar_on = False
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=3, column=0, pady=(0, t.s(24)))
        self._cancel = t.button(nav, "Cancelar", self._on_cancel, "secondary", width=t.s(340), big=True)
        self._cancel.grid(row=0, column=0, padx=t.s(14))
        self._send = t.button(nav, "ENVIAR VOTO", self._on_send, width=t.s(620), big=True)
        self._send.grid(row=0, column=1, padx=t.s(14))
        self._guard = ConfirmGuard()
        self._change_btns: list[ctk.CTkButton] = []

    def on_show(self) -> None:
        self._guard.disarm()
        for w in self._rows.winfo_children():
            w.destroy()
        self._change_btns = []
        t, c = self.t, self.c
        for i, pos in enumerate(c.ballot):
            cand = c.selected_candidate(pos)
            if cand is None:
                continue
            row = ctk.CTkFrame(self._rows, fg_color=C.SURFACE, corner_radius=t.s(18),
                               border_width=t.s(2), border_color=C.BORDER)
            row.pack(fill="x", pady=t.s(7))
            img = photos.candidate_image(cand, t.s(84))
            pic = ctk.CTkLabel(row, text="", image=img)
            pic.pack(side="left", padx=(t.s(16), t.s(18)), pady=t.s(10))
            txt = ctk.CTkFrame(row, fg_color="transparent", width=t.s(620))
            txt.pack(side="left", padx=(0, t.s(20)))
            self.label(txt, pos.title, 24, color=C.MUTED, anchor="w", width=t.s(620)).pack(anchor="w")
            self.label(txt, cand.name, 34, True, C.NAVY, anchor="w", width=t.s(620)).pack(anchor="w")
            btn = t.button(row, "Cambiar", lambda i=i: c.edit(i), "secondary",
                           width=t.s(200), compact=True)
            btn.pack(side="right", padx=t.s(18))
            self._change_btns.append(btn)

    def _on_cancel(self) -> None:
        self._guard.press(self._cancel, "Cancelar", "Toque de nuevo para cancelar", self.c.reset)

    def _on_send(self) -> None:
        # submit() bloquea el envío y notifica de forma síncrona: la UI queda
        # deshabilitada antes de que pueda procesarse otro clic.
        self.c.submit()

    def refresh(self) -> None:
        sending = self.c.phase is Phase.SUBMITTING
        self.t.set_enabled(self._send, not sending)
        self._send.configure(text="ENVIANDO…" if sending else "ENVIAR VOTO")
        self.t.set_enabled(self._cancel, not sending, "secondary")
        for b in self._change_btns:
            self.t.set_enabled(b, not sending, "secondary")
        if sending:
            self._guard.disarm()
            self._status.grid()
            if not self._bar_on:
                self._bar.start()
                self._bar_on = True
        else:
            self._status.grid_remove()
            if self._bar_on:
                self._bar.stop()
                self._bar_on = False

    def on_hide(self) -> None:
        if self._bar_on:
            self._bar.stop()
            self._bar_on = False


# --------------------------------------------------------------- resultado
class ResultScreen(Screen):
    def __init__(self, master, app) -> None:
        super().__init__(master, app)
        t = self.t
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.place(relx=0.5, rely=0.46, anchor="center")
        size = t.s(200)
        self._canvas = tk.Canvas(box, width=size, height=size, bg=C.BG, highlightthickness=0)
        self._oval = self._canvas.create_oval(4, 4, size - 4, size - 4, fill=C.OK, outline="")
        self._glyph = self._canvas.create_text(size / 2, size / 2, text="✓", fill="white",
                                               font=t.tk_font(110, True))
        self._canvas.pack(pady=(0, t.s(24)))
        self._title = self.label(box, "", 52, True, C.NAVY, wraplength=t.s(1100), justify="center")
        self._title.pack()
        self._body = self.label(box, "", 30, wraplength=t.s(1000), justify="center")
        self._body.pack(pady=(t.s(14), 0))
        self._detail = self.label(box, "", 26, color=C.MUTED, wraplength=t.s(1000), justify="center")
        self._detail.pack(pady=(t.s(10), 0))
        self._countdown = self.label(box, "", 26, color=C.MUTED)
        self._countdown.pack(pady=(t.s(14), 0))
        t.button(box, "Finalizar", self.c.reset, width=t.s(420), big=True).pack(pady=(t.s(24), 0))
        self._deadline: Optional[float] = None

    def refresh(self) -> None:
        c, r = self.c, self.c.submit_result
        self._deadline = None
        self._countdown.configure(text="")
        if c.phase is Phase.ERROR or r is None:
            glyph, color, title = "✕", C.ERR, "No fue posible continuar"
            body, detail = c.error_message, ""
        elif r.outcome is SubmitOutcome.REGISTERED:
            glyph, color, title = "✓", C.OK, "Su voto fue registrado"
            body = r.message or "Gracias por participar."
            detail = f"Comprobante: {r.receipt}" if r.receipt else ""
            self._deadline = time.monotonic() + RESULT_AUTO_RETURN_S
        elif r.outcome is SubmitOutcome.REJECTED:
            glyph, color, title = "✕", C.ERR, "Su voto no fue registrado"
            body = r.message or "El sistema rechazó el envío. Avise al personal responsable."
            detail = ""
        else:
            glyph, color, title = "!", C.WARN, "No se pudo confirmar el registro"
            body, detail = UNCERTAIN_MESSAGE, r.message
        self._canvas.itemconfig(self._oval, fill=color)
        self._canvas.itemconfig(self._glyph, text=glyph)
        self._title.configure(text=title, text_color=color)
        self._body.configure(text=body)
        self._detail.configure(text=detail)

    def tick(self) -> None:
        if self._deadline is None:
            return
        left = math.ceil(self._deadline - time.monotonic())
        if left <= 0:
            self._deadline = None
            self.c.reset()
        else:
            self._countdown.configure(text=f"Volviendo al inicio en {left} s")


# ------------------------------------------------------------------ ventana
class KioskApp(ctk.CTk):
    def __init__(self, controller: VotingController, demo: Optional[DemoHooks] = None,
                 fullscreen: bool = False, show_exit: bool = True, inactivity_s: int = 120) -> None:
        super().__init__()
        self.controller, self.demo = controller, demo
        self._inactivity_s = inactivity_s
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = (sw, sh) if fullscreen else (int(sw * 0.85), int(sh * 0.85))
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.minsize(640, 400)
        self.title("Votación electrónica · DEMOSTRACIÓN" if demo is not None else "Votación electrónica")
        self.configure(fg_color=C.BG)
        self.theme = Theme(h)
        t = self.theme

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(self, fg_color=C.NAVY, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text="Votación Electrónica", font=t.font(36, True),
                     text_color="white").pack(side="left", padx=t.s(32), pady=t.s(18))
        if show_exit:
            t.button(header, "Salir", self._close, "secondary", width=t.s(130),
                     compact=True).pack(side="right", padx=t.s(24))
        self._stage = ctk.CTkLabel(header, text="", font=t.font(26), text_color=C.HEADER_SUB)
        self._stage.pack(side="right", padx=t.s(16))

        body = ctk.CTkFrame(self, fg_color=C.BG, corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self._screens: dict[str, Screen] = {
            "welcome": WelcomeScreen(body, self), "auth": AuthScreen(body, self),
            "verified": VerifiedScreen(body, self), "loading": LoadingScreen(body, self),
            "selection": SelectionScreen(body, self),
            "review": ReviewScreen(body, self), "result": ResultScreen(body, self),
        }
        for s in self._screens.values():
            s.grid(row=0, column=0, sticky="nsew")
        self._cur: Optional[str] = None

        # Durante el desarrollo se puede salir siempre: F11, Esc, Ctrl+Q, botón Salir, cerrar ventana.
        self.bind("<F11>", lambda _e: self.attributes("-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda _e: self.attributes("-fullscreen", False))
        self.bind("<Control-q>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._last_act = time.monotonic()
        for ev in ("<Button>", "<Key>", "<Motion>"):
            self.bind_all(ev, self._touch, add="+")

        self.attributes("-fullscreen", fullscreen)
        controller.on_change = self._on_change
        self.after(0, self._start)

    def _touch(self, _event=None) -> None:
        self._last_act = time.monotonic()

    def _start(self) -> None:
        self.controller.reset()
        self._tick()

    def _show(self, name: str) -> None:
        if name == self._cur:
            return
        if self._cur:
            self._screens[self._cur].on_hide()
        self._cur = name
        self._screens[name].tkraise()
        self._screens[name].on_show()

    def _on_change(self) -> None:
        self._touch()
        phase = self.controller.phase
        name = PHASE_SCREEN[phase]
        self._show(name)
        self._stage.configure(text=STAGE_TEXT[phase])
        self._screens[name].refresh()

    def _tick(self) -> None:
        try:
            self.controller.pump()
            if self._cur:
                self._screens[self._cur].tick()
            idle = time.monotonic() - self._last_act
            if self.controller.phase in INACTIVE_PHASES and idle > self._inactivity_s:
                self.controller.reset()
        finally:
            self.after(50, self._tick)

    def _close(self) -> None:
        self.controller.on_change = None
        self.controller.shutdown()
        self.destroy()
