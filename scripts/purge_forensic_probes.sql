-- ============================================================================
-- purge_forensic_probes.sql  —  remove cross-session test/probe rows from prod
-- ============================================================================
-- FORENSIC_ROOT_CAUSE_ANALYSIS.md §17: production is polluted with probe data
-- created by earlier forensic sessions (ForensicBrand / ProofModel vehicles,
-- SYNC_* registrations, 2027 CANCELLED probe rentals, a 185-day test rental).
-- This corrupts every "does the number look right?" sanity check and the
-- vehicle-performance ranking.
--
-- USAGE — always dry-run first:
--   1.  fly postgres connect -a <db-app>            (or psql "$DATABASE_URL_SYNC")
--   2.  \i scripts/purge_forensic_probes.sql        -- runs SELECT counts only
--   3.  review the counts, then, INSIDE a transaction you control:
--         BEGIN;
--         \set do_purge 1
--         \i scripts/purge_forensic_probes.sql
--         -- inspect, then COMMIT;  (or ROLLBACK;)
--
-- Nothing is deleted unless :do_purge is set to 1.
-- ============================================================================

\if :{?do_purge}
\else
  \set do_purge 0
\endif

-- ---- identify the probe vehicles ------------------------------------------
CREATE TEMP TABLE _probe_vehicles AS
SELECT id, registration, brand, model
FROM vehicles
WHERE brand ILIKE 'Forensic%'
   OR model ILIKE 'Proof%'
   OR registration ILIKE 'SYNC\_%'   ESCAPE '\'
   OR registration ILIKE 'CRT-%'
   OR registration ILIKE 'REV-%'
   OR vin ILIKE 'SYNC%'
   OR vin ILIKE 'WREVCROSS%';

CREATE TEMP TABLE _probe_rentals AS
SELECT r.id, r.customer_name, r.start_datetime, r.num_days, r.total_price, r.status
FROM reservations r
WHERE r.vehicle_id IN (SELECT id FROM _probe_vehicles)
   OR r.customer_name IN ('Parity Test', 'Rev Test', 'X', 'Parity')
   OR r.num_days >= 180                       -- the 185-day test rental
   OR EXTRACT(YEAR FROM r.start_datetime) >= 2027;   -- future-dated probes

\echo '--- probe vehicles ---'
SELECT count(*) AS probe_vehicles FROM _probe_vehicles;
SELECT * FROM _probe_vehicles ORDER BY registration;

\echo '--- probe reservations ---'
SELECT count(*) AS probe_reservations FROM _probe_rentals;
SELECT * FROM _probe_rentals ORDER BY start_datetime;

\if :do_purge
  \echo '>>> PURGING (inside your transaction) <<<'
  DELETE FROM maintenances     WHERE vehicle_id IN (SELECT id FROM _probe_vehicles);
  DELETE FROM reservations     WHERE id         IN (SELECT id FROM _probe_rentals);
  DELETE FROM reservations     WHERE vehicle_id IN (SELECT id FROM _probe_vehicles);
  DELETE FROM vehicle_images   WHERE vehicle_id IN (SELECT id FROM _probe_vehicles);
  DELETE FROM vehicles         WHERE id         IN (SELECT id FROM _probe_vehicles);
  \echo 'Done. Review, then COMMIT or ROLLBACK.'
\else
  \echo 'DRY RUN — set :do_purge = 1 inside a transaction to delete.'
\endif

DROP TABLE _probe_vehicles;
DROP TABLE _probe_rentals;
