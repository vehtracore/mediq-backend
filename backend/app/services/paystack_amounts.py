def paystack_requested_amount_kobo(data: dict | None) -> int:
    """Return the merchant-requested amount from a Paystack transaction.

    When the customer bears Paystack fees, ``amount`` may include those fees.
    ``requested_amount`` remains the amount initialized by MDQ+.
    """
    if not data:
        return 0

    raw_amount = data.get("requested_amount")
    if raw_amount is None:
        raw_amount = data.get("amount")

    try:
        return int(raw_amount or 0)
    except (TypeError, ValueError):
        return 0
