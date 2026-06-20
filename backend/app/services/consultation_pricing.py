"""Platform-enforced pricing and payout rules for consultations."""

from decimal import Decimal, ROUND_HALF_UP

CONSULTATION_MINIMUM_FEES: dict[int, float] = {
    30: 4000.0,
}

DEFAULT_CONSULTATION_DURATION_MINUTES = 30
CONSULTATION_END_WARNING_MINUTES = 5
CONSULTATION_MESSAGE_GRACE_MINUTES = 10
SCHEDULED_JOIN_GRACE_MINUTES = 15
GENERAL_QUEUE_JOIN_GRACE_MINUTES = 5
CONSULTATION_ROOM_EARLY_ACCESS_MINUTES = 10
PLATFORM_COMMISSION_RATE = Decimal("0.37")
DOCTOR_PAYOUT_RATE = Decimal("0.63")
PAYSTACK_PLATFORM_PERCENTAGE_CHARGE = float(
    PLATFORM_COMMISSION_RATE * Decimal("100")
)
DEFAULT_CONSULTATION_FEE = CONSULTATION_MINIMUM_FEES[
    DEFAULT_CONSULTATION_DURATION_MINUTES
]


def minimum_consultation_fee(duration_minutes: int) -> float:
    try:
        return CONSULTATION_MINIMUM_FEES[duration_minutes]
    except KeyError as exc:
        raise ValueError(
            "Consultation duration must be 30 minutes."
        ) from exc


def calculate_consultation_split(amount: float) -> tuple[float, float]:
    """Return the platform commission and doctor payout in Naira."""
    normalized_amount = Decimal(str(amount)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    commission = (normalized_amount * PLATFORM_COMMISSION_RATE).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    payout = normalized_amount - commission
    return float(commission), float(payout)


def naira_to_kobo(amount: float) -> int:
    """Convert a Naira amount to an exact integer Kobo amount."""
    return int(
        (Decimal(str(amount)) * Decimal("100")).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
