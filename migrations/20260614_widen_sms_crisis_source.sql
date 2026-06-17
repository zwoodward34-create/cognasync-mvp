-- 20260614_widen_sms_crisis_source.sql
-- APPLIED 2026-06-14 to project qsnxrfefwwybiutkynzk (migration: widen_sms_crisis_source_check).
-- Allow crisis events from the SMS check-in path (and the future voice path) to be logged.
-- Previously only 'keyword' and 'help_branch' were permitted, so a check-in crisis insert
-- failed the CHECK and (because db helpers swallow errors) silently dropped the event.

alter table public.sms_crisis_events drop constraint if exists sms_crisis_events_source_check;
alter table public.sms_crisis_events add constraint sms_crisis_events_source_check
  check (source = any (array['keyword','help_branch','checkin','voice']));
