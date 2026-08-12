# pretix-csob

Payment plugin for pretix that adds ČSOB (Československá obchodní banka) as a card payment
gateway, using ČSOB's own RSA-signed payment gateway API.

## Provenance

Originally written by Nick Settler, who gave permission for this code to be reused and
relicensed freely; extracted from a published Docker image and since modified and maintained
by Jan Pohanka (see `LICENSE` for the copyright notice).

## Development setup

Same as any pretix plugin:

```bash
cd pretix-csob
pip install -e .
cd ../pretix/src && python manage.py migrate
```

Enable it per-event under Control panel → Settings → Plugins, then configure it under
Control panel → Settings → Payment → ČSOB.

## Settings

Credentials (Merchant ID, private merchant key, public bank key) can be configured at three
levels, which fall back to each other in this order: per-event → organizer-level → global
default. The organizer-level page ("ČSOB" in the organizer's sidebar) and the global defaults
exist so a multi-event organizer doesn't have to re-enter the same credentials for every event.

### Live vs. sandbox credentials

Rather than a manual "use sandbox" toggle, live and test credentials are two independent,
optional sets:

- **Merchant ID / Private Merchant Key / Public Bank Key** - live/production credentials.
- **Merchant ID / Private Merchant Key / Public Bank Key (sandbox)** - credentials for ČSOB's
  test gateway.

Either set, both, or neither may be filled in at each settings level; whichever set is
non-empty gets validated against ČSOB's `echo` endpoint when the settings form is saved.

Which set is actually used is picked automatically, following the same convention pretix's
bundled Stripe plugin uses:

- While placing an order (before an `Order`/`OrderPayment` exists yet - `execute_payment`,
  `is_enabled`, checkout rendering), the event's own test-mode toggle
  (Control panel → Settings → General → "Enable test mode") decides.
- Once an order exists (the payment return/status-check callbacks), the *order's* `testmode`
  flag is used instead of the event's current toggle state, since an order keeps the mode it
  was actually placed in even if the event's toggle changes later.

If an event is in test mode but no sandbox credentials are configured, ČSOB is reported as
disabled rather than silently falling back to live credentials.

## Known limitations

- ČSOB's API is called with a single flat "Tickets" cart line for the payment's total amount,
  not itemized per order position.
- Customer name/e-mail/phone are not sent to ČSOB as part of the payment request.
