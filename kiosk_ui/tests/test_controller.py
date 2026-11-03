"""Pruebas del flujo, del doble envío y del resultado incierto (sin Tkinter).

Ejecutar desde la raíz del proyecto:  python -m unittest kiosk_ui.tests.test_controller -v
"""
import time
import unittest

from kiosk_ui.adapters import mock
from kiosk_ui.adapters.mock import BALLOT, MockKit
from kiosk_ui.core.controller import Services, VotingController
from kiosk_ui.core.models import Phase, Step, StepStatus, SubmitOutcome


def wait_for(ctrl, cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ctrl.pump()
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError(f"Tiempo agotado; fase={ctrl.phase}, pasos={ctrl.steps}")


class FlowTestCase(unittest.TestCase):
    def setUp(self):
        self.kit = MockKit(delay=0.01)
        self.ctrl = VotingController(self.kit.services())
        self.ctrl.reset()
        wait_for(self.ctrl, self.kit.waiting.is_set)

    def tearDown(self):
        self.ctrl.shutdown()

    def tap(self, scenario):
        self.assertTrue(self.kit.tap(scenario.label))

    def login(self, scenario=mock.HAPPY):
        self.tap(scenario)
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.VERIFIED)
        self.ctrl.continue_to_ballot()
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.SELECTING)

    def choose_all(self):
        for pos in self.ctrl.ballot:
            self.ctrl.select(pos.id, pos.candidates[0].id)
            self.ctrl.next_position()
        self.assertIs(self.ctrl.phase, Phase.REVIEW)


class TestHappyPath(FlowTestCase):
    def test_full_flow_registers_vote(self):
        self.login()
        self.assertEqual(len(self.ctrl.ballot), len(BALLOT))
        self.choose_all()
        self.assertTrue(self.ctrl.submit())
        self.assertIs(self.ctrl.phase, Phase.SUBMITTING)
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.RESULT)
        self.assertIs(self.ctrl.submit_result.outcome, SubmitOutcome.REGISTERED)
        self.assertEqual(self.kit.submit_count, 1)
        # El envío contiene exactamente la selección hecha.
        self.assertEqual(self.kit.submitted[0], {p.id: p.candidates[0].id for p in BALLOT})
        # Tras el resultado no queda nada de la selección en memoria.
        self.assertEqual(self.ctrl.selections, {})

    def test_cannot_continue_without_selection(self):
        self.login()
        self.ctrl.next_position()
        self.assertEqual(self.ctrl.position_index, 0)
        self.assertFalse(self.ctrl.can_continue)

    def test_nothing_sent_before_explicit_submit(self):
        self.login()
        self.choose_all()
        time.sleep(0.1)
        self.ctrl.pump()
        self.assertEqual(self.kit.submit_count, 0)

    def test_change_selection_from_review(self):
        self.login()
        self.choose_all()
        self.ctrl.edit(1)
        self.assertIs(self.ctrl.phase, Phase.SELECTING)
        pos = self.ctrl.current_position
        self.ctrl.select(pos.id, pos.candidates[1].id)
        self.ctrl.next_position()
        self.assertIs(self.ctrl.phase, Phase.REVIEW)
        self.assertEqual(self.ctrl.selections[pos.id], pos.candidates[1].id)


class TestSubmitSafety(FlowTestCase):
    def test_double_submit_is_ignored(self):
        self.login()
        self.choose_all()
        self.assertTrue(self.ctrl.submit())
        self.assertFalse(self.ctrl.submit())
        self.assertFalse(self.ctrl.submit())
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.RESULT)
        self.assertFalse(self.ctrl.submit())
        self.assertEqual(self.kit.submit_count, 1)

    def test_reset_is_ignored_while_submitting(self):
        self.login()
        self.choose_all()
        self.ctrl.submit()
        self.ctrl.reset()
        self.assertIs(self.ctrl.phase, Phase.SUBMITTING)
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.RESULT)
        self.assertIs(self.ctrl.submit_result.outcome, SubmitOutcome.REGISTERED)

    def test_uncertain_result_is_never_retried(self):
        self.login(mock.UNCERTAIN)
        self.choose_all()
        self.ctrl.submit()
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.RESULT)
        self.assertIs(self.ctrl.submit_result.outcome, SubmitOutcome.UNCERTAIN)
        self.assertFalse(self.ctrl.submit())
        time.sleep(0.1)
        self.ctrl.pump()
        self.assertEqual(self.kit.submit_count, 1)

    def test_backend_rejection_is_reported(self):
        self.login(mock.ALREADY_VOTED)
        self.choose_all()
        self.ctrl.submit()
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.RESULT)
        self.assertIs(self.ctrl.submit_result.outcome, SubmitOutcome.REJECTED)


class TestErrors(FlowTestCase):
    def test_exception_on_submit_is_uncertain_not_success(self):
        class Boom:
            def load_ballot(self, ref):
                return BALLOT

            def submit_vote(self, ref, selections):
                raise ConnectionError("simulado")

        k = self.kit
        ctrl = VotingController(Services(k.card_reader, k.fingerprint, k.face, Boom()))
        self.ctrl.shutdown()
        ctrl.reset()
        wait_for(ctrl, k.waiting.is_set)
        k.tap(mock.HAPPY.label)
        wait_for(ctrl, lambda: ctrl.phase is Phase.VERIFIED)
        ctrl.continue_to_ballot()
        wait_for(ctrl, lambda: ctrl.phase is Phase.SELECTING)
        for pos in ctrl.ballot:
            ctrl.select(pos.id, pos.candidates[0].id)
            ctrl.next_position()
        ctrl.submit()
        wait_for(ctrl, lambda: ctrl.phase is Phase.RESULT)
        self.assertIs(ctrl.submit_result.outcome, SubmitOutcome.UNCERTAIN)
        ctrl.shutdown()

    def test_card_rejected(self):
        self.tap(mock.CARD_FAIL)
        wait_for(self.ctrl, lambda: self.ctrl.failed_step is Step.CARD)
        self.assertIs(self.ctrl.steps[Step.CARD], StepStatus.FAILED)

    def test_fingerprint_failure_and_retry_and_cancel(self):
        self.tap(mock.FINGER_FAIL)
        wait_for(self.ctrl, lambda: self.ctrl.failed_step is Step.FINGERPRINT)
        self.assertIs(self.ctrl.steps[Step.CARD], StepStatus.OK)
        self.assertIs(self.ctrl.steps[Step.FACE], StepStatus.PENDING)
        self.ctrl.retry_step()
        self.assertIs(self.ctrl.steps[Step.FINGERPRINT], StepStatus.ACTIVE)
        wait_for(self.ctrl, lambda: self.ctrl.failed_step is Step.FINGERPRINT)
        self.ctrl.reset()
        self.assertIs(self.ctrl.phase, Phase.IDLE)
        self.assertEqual(self.ctrl.steps[Step.CARD], StepStatus.PENDING)

    def test_face_failure(self):
        self.tap(mock.FACE_FAIL)
        wait_for(self.ctrl, lambda: self.ctrl.failed_step is Step.FACE)
        self.assertIs(self.ctrl.steps[Step.FINGERPRINT], StepStatus.OK)

    def test_ballot_load_error(self):
        self.tap(mock.BALLOT_FAIL)
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.VERIFIED)
        self.ctrl.continue_to_ballot()
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.ERROR)
        self.assertTrue(self.ctrl.error_message)

    def test_reset_after_error_waits_for_new_card(self):
        self.tap(mock.BALLOT_FAIL)
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.VERIFIED)
        self.ctrl.continue_to_ballot()
        wait_for(self.ctrl, lambda: self.ctrl.phase is Phase.ERROR)
        self.ctrl.reset()
        wait_for(self.ctrl, self.kit.waiting.is_set)
        self.login()


if __name__ == "__main__":
    unittest.main()
