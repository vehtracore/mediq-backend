/// API Keys & SDK constants for MDQ+ frontend.
///
/// ⚠️  NEVER commit real production keys to source control.
/// Replace the test key below with your live key in your CI/CD
/// environment before deploying to production.
library;

// NOTE: The Paystack Secret Key has been removed from the client.
// All payment initialization is handled server-side via
//   POST /api/v1/payments/initialize
// The frontend only holds the Public Key below for reference; it is NOT
// passed to any SDK call — the backend returns an authorization_url instead.
const String paystackPublicKey = 'pk_test_5e33cafde60e1d571c9bc31539df71796bf60d14';
// ↑ Replace with your actual key from https://dashboard.paystack.com/#/settings/developer

// Paystack recurring Plan Codes — safe to store on the client (not secret).
// These are passed to the backend /initialize endpoint so Paystack can create
// a recurring subscription instead of a one-time charge.
const String individualPlanCode = 'PLN_cdi2rapcohe8zst';
const String familyPlanCode = 'PLN_vs1as05c6302132';
