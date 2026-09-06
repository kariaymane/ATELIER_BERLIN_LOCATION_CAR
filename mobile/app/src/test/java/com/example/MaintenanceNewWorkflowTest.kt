package com.example

import com.example.data.model.MaintenanceTicket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * The new Maintenance model on Mobile — identical in meaning to the Desktop.
 *
 * A maintenance is a PERIOD, not a sequence of steps:
 *
 *   now  <  end  ->  EN COURS
 *   now >=  end  ->  TERMINÉE
 *
 * There is no Diagnostic / Réparation / Test / Finalisée stage, and no manual
 * action ("étape suivante", "finaliser") that advances one. The status is
 * derived from the clock, so a ticket becomes TERMINÉE on its own.
 *
 * The old `MaintenanceStep` enum no longer exists; this file compiling at all
 * is part of the proof.
 */
class MaintenanceNewWorkflowTest {

    private fun iso(offsetHours: Long): String =
        Instant.now().plus(offsetHours, ChronoUnit.HOURS).toString()

    private fun ticket(
        start: String = iso(-24),
        expectedEnd: String? = iso(24),
        actualEnd: String? = null,
        status: String = "ACTIVE",
    ) = MaintenanceTicket(
        id = "m1",
        vehicleId = "v1",
        vehicleName = "BMW 320d",
        vehiclePlate = "1234-A-56",
        serviceItem = "Accident",
        description = "Choc avant / remplacement pare-chocs",
        startIso = start,
        expected_end_datetime = expectedEnd,
        actual_end_datetime = actualEnd,
        status = status,
    )

    // ── Time-derived status ───────────────────────────────────────────

    @Test
    fun `a maintenance whose end is in the future is EN COURS`() {
        val t = ticket(start = iso(-24), expectedEnd = iso(24))
        assertFalse(t.isCompleted)
        assertEquals("En cours", t.effectiveStatusDisplay)
    }

    @Test
    fun `a maintenance whose end has passed is TERMINEE without any action`() {
        val t = ticket(start = iso(-48), expectedEnd = iso(-1))
        assertTrue(t.isCompleted)
        assertEquals("Terminée", t.effectiveStatusDisplay)
    }

    @Test
    fun `a maintenance closed early by the server is TERMINEE`() {
        val t = ticket(expectedEnd = iso(48), status = "COMPLETED")
        assertTrue(t.isCompleted)
        assertEquals("Terminée", t.effectiveStatusDisplay)
    }

    @Test
    fun `a real end instant wins over the planned one`() {
        val t = ticket(expectedEnd = iso(48), actualEnd = iso(-1))
        assertEquals(t.actual_end_datetime, t.effectiveEndIso)
        assertTrue(t.isCompleted)
    }

    @Test
    fun `the planned end is used when no real end was recorded`() {
        val t = ticket(expectedEnd = iso(24), actualEnd = null)
        assertEquals(t.expected_end_datetime, t.effectiveEndIso)
    }

    @Test
    fun `a maintenance with no end at all stays EN COURS`() {
        val t = ticket(expectedEnd = null, actualEnd = null)
        assertFalse(t.isCompleted)
        assertEquals("En cours", t.effectiveStatusDisplay)
    }

    @Test
    fun `a cancelled maintenance reports as annulee`() {
        val t = ticket(status = "CANCELLED")
        assertTrue(t.isCancelled)
        assertEquals("Annulée", t.effectiveStatusDisplay)
    }

    // ── Only two states exist ─────────────────────────────────────────

    @Test
    fun `the status vocabulary is limited to the new model`() {
        val allowed = setOf("En cours", "Terminée", "Annulée")
        val cases = listOf(
            ticket(expectedEnd = iso(24)),
            ticket(expectedEnd = iso(-1)),
            ticket(status = "COMPLETED"),
            ticket(status = "CANCELLED"),
            ticket(expectedEnd = null),
        )
        cases.forEach { t ->
            assertTrue(
                "unexpected status '${t.effectiveStatusDisplay}'",
                t.effectiveStatusDisplay in allowed
            )
        }
    }

    @Test
    fun `no old workflow stage survives as a status`() {
        val banned = listOf("Diagnostic", "Réparation", "Reparation",
                            "Contrôle", "Controle", "Test", "Finalisée", "En attente")
        val t = ticket()
        assertFalse(t.effectiveStatusDisplay in banned)
    }

    // ── The reason shown to the user ──────────────────────────────────

    @Test
    fun `the motif falls back to the maintenance type`() {
        val t = ticket()
        assertEquals("Accident", t.motif)
    }

    @Test
    fun `an explicit title is used as the motif`() {
        val t = ticket().copy(title = "Choc avant")
        assertEquals("Choc avant", t.motif)
    }

    @Test
    fun `a blank title falls back rather than showing nothing`() {
        val t = ticket().copy(title = "   ")
        assertEquals("Accident", t.motif)
    }

    // ── List filters use the new model, not old stages ────────────────

    @Test
    fun `the three list filters partition the tickets`() {
        val inProgress = ticket(expectedEnd = iso(24))
        val finished = ticket(expectedEnd = iso(-1))
        val cancelled = ticket(status = "CANCELLED")
        val all = listOf(inProgress, finished, cancelled)

        assertEquals(3, all.filter { true }.size)
        assertEquals(
            listOf(inProgress),
            all.filter { !it.isCompleted && !it.isCancelled }
        )
        assertEquals(listOf(finished), all.filter { it.isCompleted })
    }
}
