// Stripe receipts are the confirmation path. Optional app email must not gate fulfillment.
export async function completePaidPurchase(
  fulfill: () => Promise<void>,
  sendOptionalConfirmation: () => Promise<void>,
  logFailure: (error: unknown) => void,
) {
  await fulfill();
  try {
    await sendOptionalConfirmation();
  } catch (error) {
    logFailure(error);
  }
}