/// API Keys & SDK constants for MDQ+ frontend.
///
/// ⚠️  NEVER commit real production keys to source control.
/// Replace the test key below with your live key in your CI/CD
/// environment before deploying to production.
library;

/// Paystack public key — used exclusively by the client-side SDK.
/// The secret key lives on the backend only and is NEVER shipped here.
const String paystackPublicKey = 'pk_test_5e33cafde60e1d571c9bc31539df71796bf60d14';
// ↑ Replace with your actual key from https://dashboard.paystack.com/#/settings/developer
const String paystackSecretKey = 'sk_test_5d8e96db2f7df49a89cb1c77777b277c43cda48f';
