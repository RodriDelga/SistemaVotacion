"""Smoke test gráfico con Xvfb; no es una prueba física ni táctil."""
from __future__ import annotations

import time

from kiosk_ui.adapters.mock import HAPPY, MockKit
from kiosk_ui.core.controller import VotingController
from kiosk_ui.core.models import Phase, SubmitOutcome
from kiosk_ui.ui.app_window import KioskApp

kit = MockKit(delay=0.01)
controller = VotingController(kit.services())
app = KioskApp(controller, demo=kit, fullscreen=False, show_exit=True, inactivity_s=30)
started = time.monotonic()


def drive():
    if controller.phase is Phase.IDLE:
        kit.tap(HAPPY.label)
    elif controller.phase is Phase.VERIFIED:
        controller.continue_to_ballot()
    elif controller.phase is Phase.SELECTING:
        pos = controller.current_position
        controller.select(pos.id, pos.candidates[0].id)
        controller.next_position()
    elif controller.phase is Phase.REVIEW:
        controller.submit()
    elif controller.phase is Phase.RESULT:
        assert controller.submit_result.outcome is SubmitOutcome.REGISTERED
        assert kit.submit_count == 1
        print("UI_SMOKE_OK: bienvenida → identidad → boleta → revisión → confirmación")
        app._close()
        return
    if time.monotonic() - started > 15:
        app._close()
        raise RuntimeError(f"Timeout de UI en {controller.phase}")
    app.after(100, drive)


app.after(300, drive)
app.mainloop()
