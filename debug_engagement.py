"""
Quick debug script — run from the cognasync-mvp directory:
    python debug_engagement.py

Prints what _get_engagement_flags and compute_engagement_stats return
for each patient so you can see why badges are or aren't showing.
"""
import os, sys, json
from dotenv import load_dotenv
load_dotenv()

import database as db

def main():
    # Fetch all patients for the first provider found
    try:
        res = db.supabase_admin.table('users') \
            .select('id, email, role') \
            .eq('role', 'provider') \
            .limit(5).execute()
        providers = res.data or []
    except Exception as e:
        print(f"Could not fetch providers: {e}")
        sys.exit(1)

    if not providers:
        print("No providers found.")
        sys.exit(0)

    for prov in providers:
        print(f"\n=== Provider: {prov['email']} ===")
        patients = db.get_provider_patients_with_stats(prov['id'])
        if not patients:
            print("  No patients.")
            continue

        for p in patients:
            pid = p.get('patient_id') or p.get('id', '')
            name = p.get('full_name', 'Unknown')
            print(f"\n  Patient: {name} ({pid})")

            # Raw engagement stats
            stats = db.compute_engagement_stats(pid, days=14)
            if stats:
                print(f"    sms_by_flow keys:    {list(stats.get('sms_by_flow', {}).keys())}")
                all_sent = sum(fs['sent'] for fs in stats.get('sms_by_flow', {}).values())
                all_resp = sum(fs['responded'] for fs in stats.get('sms_by_flow', {}).values())
                print(f"    all_sms_sent:        {all_sent}")
                print(f"    all_sms_responded:   {all_resp}")
                print(f"    overall_sms_rate:    {stats.get('overall_sms_rate')}")
                print(f"    extended_no_response:{stats.get('extended_no_response')}")
                print(f"    insufficient_data:   {stats.get('insufficient_data')}")
                print(f"    never_responded:     {stats.get('never_responded')}")
                print(f"    complete_absence:    {stats.get('complete_absence')}")
                print(f"    sms_divergent:       {stats.get('sms_divergent')}")
            else:
                print(f"    compute_engagement_stats returned None")

            # Flags dict (what the dashboard sees)
            try:
                flags = db.get_patient_flags(pid, days=30)
                eng = flags.get('engagement')
                print(f"    get_patient_flags engagement: {json.dumps(eng, indent=6) if eng else None}")
            except Exception as e:
                print(f"    get_patient_flags EXCEPTION: {e}")

if __name__ == '__main__':
    main()
