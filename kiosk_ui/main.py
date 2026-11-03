"""Punto de entrada de kiosk_ui: adaptadores reales por defecto, demo opcional.

    python -m kiosk_ui.main                 # integración real
    python -m kiosk_ui.main --demo          # simulación completa, sin hardware
    python -m kiosk_ui.main --fullscreen    # pantalla completa en Raspberry Pi
"""
from __future__ import annotations

import argparse
import logging

import customtkinter as ctk

from kiosk_ui.core.controller import VotingController
from kiosk_ui.ui.app_window import KioskApp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Interfaz de votación CustomTkinter")
    parser.add_argument("--demo", action="store_true", help="usar adaptadores simulados")
    parser.add_argument("--fullscreen", action="store_true", help="iniciar en pantalla completa")
    parser.add_argument("--delay", type=float, default=1.2, help="demora base solo en modo demo")
    parser.add_argument("--inactivity", type=int, default=120, help="segundos antes de volver al inicio")
    parser.add_argument("--show-exit", action="store_true", help="mostrar Salir durante pruebas")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    if args.demo:
        from kiosk_ui.adapters.mock import MockKit
        kit = MockKit(delay=args.delay)
        services, demo = kit.services(), kit
    else:
        from kiosk_ui.adapters.real.services import build_real_services
        services, demo = build_real_services(), None
    controller = VotingController(services)
    app = KioskApp(controller, demo=demo, fullscreen=args.fullscreen,
                   show_exit=args.show_exit or args.demo, inactivity_s=args.inactivity)
    app.mainloop()


if __name__ == "__main__":
    main()
