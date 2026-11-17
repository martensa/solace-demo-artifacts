# GEBIT Purchase API 2.50.0: analysis for the EuroCIS showcase "Preis- und Aktionsagent mit Freigabe"

Track: GEBIT Purchase API deep analysis (read-only research, 2026-11-10).

Legend used throughout:

- **VERIFIED**: read in a source file (cited as `file:line`), observed in a GEBIT sample, or
  reproduced with a command (the command is named).
- **ASSUMPTION**: my inference. Needs confirmation by GEBIT or by a test in their demo lab.

Abbreviations for source paths:

- `P/` = `.../scratchpad/gebit/purchase/de/gebit/rp/purchase/purchase/v2/`
- `R/` = `.../scratchpad/gebit/receipt/de/gebit/rp/receipt/receipt/v2/datatype/`
- `S/NN_*.json` = `.../scratchpad/gebit/events/events_simpleSale/NN_<Event>.json`
- `simpleSale.json` = the final receipt JSON GEBIT supplied (identical to `~/Downloads/Gebit/simpleSale.json`, `cmp` says SAME)

How I checked things: besides reading every purchase proto plus the receipt protos, I loaded GEBIT's binary
descriptor sets (`~/Downloads/Gebit/purchase-api-2.50.0.pb`, `receipt-api-2.13.0.pb`) with the
local `python3 -I` protobuf 6.33.5 runtime. The helper scripts live in
`.../scratchpad/tools/` (outside the GEBIT dirs), and GEBIT files were only read as data. Results:

- **VERIFIED**: all 11 simple-sale JSON files parse into their `@type` message with no errors
  (`decode_gebit.py`), so they are the canonical proto3 JSON mapping of `google.protobuf.Any`.
- **VERIFIED**: `PurchaseTransactionClosed.serializedReceiptContent` decodes as base64, then as a
  binary `google.protobuf.Any` with type_url `type.googleapis.com/de.gebit.rp.receipt.receipt.v2.datatype.Receipt`
  (3040 bytes). It is the same receipt as `simpleSale.json`, and it has zero unknown fields against
  the 2.13.0 receipt descriptor, although the event says `serializedReceiptVersion: "2.14.0-I114"`.
- **VERIFIED**: the service has 106 RPCs. All of them are unary, none streams, and 3 are deprecated
  (`VoidAddArticlePosition`, `AssignCustomerData`, `RemoveCustomerData`) (`svc.py`).
- **VERIFIED**: there are 114 event messages plus the common `Header`. 110 of them carry the custom
  message option `(de.gebit.rp.protobuf.options.async_message_set) = "PurchaseDomainEvents"`
  (extension 52548 on `MessageOptions`). Four carry no option: `ExtensionPropertiesAdded`,
  `AnonymousCouponsRemoved`, `AnonymousCouponVoided` and `ReferencedPaymentSessionInformationAdded`
  (`decode_gebit.py`, `catalog.py`).
- **VERIFIED**: every GEBIT-schema JSON example of my own in section 8 (8.1-8.6) was
  validated against the GEBIT descriptor sets (`validate_examples.py`; re-checked on
  2026-11-17 after the examples moved to simulator values).
- **VERIFIED**: the extracted proto source tree does not include the imported
  `de/gebit/rp/protobuf/{options,basic,formatted_content}/*.proto` (they are missing from the zip as
  well). `protoc` on the sources alone therefore fails, but the `.pb` descriptor sets are
  self-contained and are what a simulator should build on.

---

## 0. TL;DR for the showcase design

1. **The scan event is `PositionAdded`**, not "ArticleAdded". It carries `articleId`, `articleNumber`,
   `description`, `itemCount`, `capturingInformation` (EAN/scan method) and a `pricingInformation`
   with basket total, taxes and per-position base/effective value and discounts. This is the trigger
   for "follow every scan live" (`P/event/basket_event.proto:33-86`, observed in `S/03_PositionAdded.json`).
2. **Finality**: everything up to `PurchaseTransactionClosed` is provisional. `Closed` carries the
   complete final receipt (`serializedReceiptContent`, binary protobuf `Any` inside base64, even
   in JSON). `PurchaseTransactionCancelled` means not sold, and `PurchaseTransactionSuspended`
   means not sold yet (it can be resumed later as a new transaction id). A later
   `VoidPurchaseTransaction` creates a separate transaction of type VOID that reverses a closed
   receipt (section 2).
3. **The POS never gets the position id synchronously.** `AddArticle` returns
   `google.protobuf.Empty` (`P/service/purchase_transaction_service.proto:100`). The client has to
   read `PositionAdded` to learn `positionId` before it can line-void or discount that line. The
   correlation key from command to events is `header.trace_id` -> `metadata.traceId` (observed: all
   events of one command share the trace id).
4. **There is no price-change command in the Purchase API.** The price comes from master data
   unless the POS overrides it (`SuppliedPriceInformation`: when it is absent, the master-data
   unit price applies, `P/datatype/basket_datatype.proto:217-233`). The receipt records the price
   origin in `priceSource` (sample: `"freezePrice"`). "The approved price applies at the next scan"
   is therefore realistically **a change in article master / price service, picked up by the next
   `AddArticle`**, not a POS command. That matches the GEBIT developer's note about a price-change
   event to the article master data service.
5. **"Actions" (`action_*.proto`) are not promotions (Aktionen).** They are technical
   *closing actions* run while a receipt is closed, with failed ones acknowledged or retried
   (`P/datatype/action_datatype.proto:20-57`). Promotions show up as `CapturedPromotion.promotion_code`,
   `PositionDiscount`/`SetDiscount`, `PromotionActionTrigger` and `PromotionPaymentPosition`,
   computed by GEBIT's pricing/promotion engine.
6. **"Mesh" (`mesh_*.proto`) is a till mesh, not the Solace Event Mesh.** It lets several tills
   share and claim one purchase transaction (claim, lock, unlock, force-claim, anchor). Avoid the
   word clash in the talk track.
7. **A voucher on the receipt has a native place**: `Receipt.loyalty.loyaltyPurchaseResult.checkoutCoupons[]`
   (`CheckoutCoupon`: a coupon that is printed once the checkout finishes, with
   `printContent` that can hold a QR barcode, `R/loyalty_datatype.proto:242-255`). The loyalty or
   promotion side fills it during closing. The public API has **no hook** that lets an external
   service add a closing action. For the showcase, issue the next-visit voucher after `Closed`
   (shown on the monitor or app) and redeem it on the next visit via `ApplyAnonymousCoupon` or
   `AssignLoyaltyCoupon`.
8. **Approval is native**: every command header has an optional `approver`
   (`P/command/common_command.proto:40-45`), and the transaction or receipt keeps `approvals[]`
   with `approverId`, `approvedAt` and `approvedCommand` (`P/datatype/purchase_transaction_datatype.proto:282-295`,
   `R/receipt_datatype.proto:254-264`). This lets the human-in-the-loop story use GEBIT's own data model.
9. **Wire format**: use GEBIT's own proto3 JSON (with `@type`) on the raw topics. SAM consumes JSON
   natively, and the entrypoint's `protobuf` message format has no descriptor setting. Add a slim
   per-scan and per-receipt "digest" topic for SAM. This keeps tokens down, stays under the MCP
   2048-byte artifact threshold, decodes the binary receipt and keeps the payload ASCII-only.

---

## 1. Event catalog relevant for a sale

### 1.1 Common envelope (all events)

- `header` (`event.Header`): only `eventTimestamp`, which is the time the aggregate event was
  *mapped* to the protobuf event, not its creation time (`P/event/common_event.proto:20-28`).
- `metadata` (`datatype.Metadata`): `offset` (int64, puts the events in sequence),
  `creationTimestamp`, `traceId` (`P/datatype/common_datatype.proto:21-32`).
- `purchaseTransactionId` (string, UUID in the sample) and, in most events,
  `purchaseTransactionStatus` and an optional `pricingInformation`.
- `extensionProperties[]` (`Property{key, typedValue}`).

### 1.2 Two event families (important design choice)

**VERIFIED** (`P/event/purchase_transaction_event.proto:24-105`). The two families:

- **Low-granularity, preferred by GEBIT**:
  - `PurchaseTransactionChanged{purchaseTransactionId, transaction: PurchaseTransaction, extensionProperties}`
    carries the *full* state. It is **not guaranteed 1:1 per command**: quick successive commands
    can collapse into one event, but ordering is guaranteed (lines 31-37).
  - `PurchaseTransactionFinalized{finalizedAt, purchaseTransactionStatus, serializedReceiptFormat, serializedReceiptContent, serializedReceiptVersion}`.
    It is guaranteed to arrive before the matching `PurchaseTransactionChanged` that moves into
    a final state (lines 71-74).
- **High-granularity, one event per change**: everything else below. Every one of them carries a
  note pointing to the newer low-granularity events as the better choice for many use cases.

The GEBIT sample contains only high-granularity events. **ASSUMPTION**: the demo lab can emit both
families. Ask GEBIT which ones are switched on.

### 1.3 Transaction lifecycle (`purchase_transaction_event.proto`, `financial_transaction_event.proto`)

| Event | Key fields (beyond envelope) | Status carried | Source |
|---|---|---|---|
| `PurchaseTransactionCreated` | `location`, `currency`, `createdAt`, `employeeId`, `cashdrawerId`, `employeeSessionId`, `applicationMode` | CREATED | OBSERVED `S/01` |
| `PurchaseTransactionOpened` | `openedAt`, **`receiptNumber`** | OPEN | OBSERVED `S/02` (first `AddArticle`) |
| `PurchaseTransactionInCharging` `FinancialTransaction` | only envelope | IN_CHARGING_FINANCIAL_TRANSACTION | OBSERVED `S/09` |
| `PurchaseTransactionInClosing` | only envelope | IN_CLOSING | OBSERVED `S/10` |
| `PurchaseTransactionClosed` | `closedAt`, `serializedReceiptFormat` ("PROTOBUF"), `serializedReceiptContent` (bytes), `serializedReceiptVersion` | CLOSED | OBSERVED `S/11` |
| `PurchaseTransactionInCancellation` | `cancellationReason`, `cancellationReasonCode` | IN_CANCELLATION | proto :447 |
| `PurchaseTransactionCancelled` | `cancelledAt`, serialized receipt (CanceledReceipt) | CANCELLED | proto :237 |
| `PurchaseTransactionInSuspension` | only envelope | IN_SUSPENSION | proto :478 |
| `PurchaseTransactionSuspended` | `suspendedAt`, serialized receipt (SuspendedReceipt with `resume_data`) | SUSPENDED | proto :323 |
| `PurchaseTransactionRecovered` | like Created (location, employee, cashdrawer ...) | (new tx) | proto :278 |
| `ReturnReasonAssigned` / `VoidReasonAssigned` | `returnReason[Code]` / `voidReason[Code]` | any | proto :360/:391 |
| `ExtensionPropertiesAdded` | `extensionPropertyBearerType`, `extensionPropertyBearerId`, `extensionProperties` | any | proto :503 (no async option!) |
| `PurchaseTransactionChanged` / `Finalized` | see 1.2 | any / final | proto :39/:76 |

No event is named "Voided" or "Resumed". Voiding a closed receipt (`VoidPurchaseTransaction[ByReceiptNumber]`)
and resuming a suspended one (`ResumePurchaseTransaction[ByReceiptNumber]`) both **create a new
purchase transaction**: the RPC returns a new `PurchaseTransactionId`
(`P/service/purchase_transaction_service.proto:76-88`). The new transaction has type VOID or SALE
and a `receipt_reference` of type VOID or RESUME (`P/datatype/purchase_transaction_enum.proto:124-138`).
**VERIFIED**: the high-granularity `PurchaseTransactionCreated` does **not** carry
`purchase_transaction_type`. Only `PurchaseTransaction.purchase_transaction_type` (in `Changed`)
and `Receipt.receipt_type` (sample: `"SALE"`) tell a void apart from a sale.

### 1.4 Positions (`basket_event.proto`)

| Event | Key fields | Triggered by (command) |
|---|---|---|
| `PositionAdded` | `positionId`, `articlePositionType` (SALE/RETURN/DEPOSIT_SALE/...), `articleId`, `articleNumber`, `itemCount`, `description`, `pricingInformation`, `createdAt`, `returnProperties`, `dimensionInformation`, `capturingInformation`, `agencyId` | `AddArticle`, `ReturnArticle*` |
| `ArticlePositionsAdded` | `articlePositionIds[]` only (no article details), `createdAt` | `AddArticles` (bulk) |
| `ArticlePositionReplaced` | like PositionAdded | `ReplaceSimpleArticleInPosition` |
| `ArticlePositionItemCountChanged` | `positionId`, `itemCount` (new absolute count) | `ChangeArticlePositionItemCount` |
| `ArticlePositionVoided` / `ArticlePositionUnvoided` | `positionId` | `VoidArticlePosition(s)` / `UnvoidArticlePosition` |
| `ArticlePositionPriceOverridden` | `positionId`, `newPrice`, `newPricePerUnit`, `reason`, `reasonCode` | `OverrideArticlePositionPrice` |
| `PercentageArticlePositionDiscountApplied` | `positionId`, `percentageDiscount`, `reason`, `reasonCode` | `ApplyPercentageArticlePositionDiscount` |
| `AbsoluteArticlePositionDiscountApplied` | `positionId`, `absoluteDiscount` (per item), `reason`, `reasonCode` | `ApplyAbsoluteArticlePositionDiscount` |
| `PercentageBasketDiscountApplied` / `AbsoluteBasketDiscountApplied` | `percentageDiscount` / `absoluteDiscount`, `reason`, `reasonCode` | `Apply{Percentage,Absolute}BasketDiscount` |
| `RequestedManualArticlePositionDiscountRemoved` / `RequestedManualBasketDiscountRemoved` | `positionId` / - | `RemoveRequestedManual*Discount` |
| `ArticlePositionPromotionApplied` / `ArticlePositionPromotionRemoved` | `positionId`, `capturedPromotion.promotionCode` | `ApplyArticlePositionPromotion` / `RemoveArticlePositionPromotion` |
| `ArticlePositionReturnReasonAssigned` | `positionId`, `returnReasonCode` | `AssignArticlePositionReturnReason` |
| `SubTotalPositionAdded` (sub_total_event) | `subTotalPositionId`, `createdAt` | `AddSubTotal` |

(`P/event/basket_event.proto:33-644`, `P/event/sub_total_event.proto`.) **VERIFIED**: there is
no separate event for an implicit promotion that the pricing engine applies (for example
"2 for 1"). Its effect is visible only inside `pricingInformation`
(`articlePositions[].positionDiscounts[]`, `setDiscounts[]`). The commented-out
`// Deferred: promotion actions` (`P/datatype/purchase_transaction_datatype.proto:188-189`) shows
that GEBIT has not exposed a list of promotion actions.

### 1.5 Customer / loyalty (`customer_event.proto`, `loyalty_event.proto`)

| Event | Key fields | Command |
|---|---|---|
| `CustomerAssigned` / `CustomerRemoved` | `customer: CustomerData{customerId, customerName, customerNumber, customerType, customerAddresses[], vatId, capturingInformation}` | `AssignCustomer` (fails if a customer is already set) / `RemoveCustomer` |
| `CustomerDataAssigned` / `CustomerDataRemoved` | `customerId` (deprecated path) | `AssignCustomerData` / `RemoveCustomerData` (deprecated) |
| `LoyaltyMembershipAssigned` | `membershipPositionId`, `capturingInformation`, `paymentSessionSums` (if in payment) | `AssignLoyaltyMembership(membership_identification_value)` |
| `LoyaltyMembershipVoided` | `membershipPositionId` | `VoidLoyaltyMembership` |
| `LoyaltyCouponAssigned` / `LoyaltyCouponVoided` | `membershipPositionId`, `couponPositionId` | `AssignLoyaltyCoupon(coupon_identification_value)` / `VoidLoyaltyCoupon` |
| `UnverifiedLoyaltyCouponAssigned` / `...Voided` / `...Removed` | `couponPositionId` | coupon scanned before the membership (converted when a membership arrives) |
| `AnonymousCouponApplied` | `prefix`, `promotionCode`, `couponPositionId`, `paymentSessionSums`, `capturingInformation` | `ApplyAnonymousCoupon(prefix, promotion_code)` |
| `AnonymousCouponsRemoved` / `AnonymousCouponVoided` | removed coupons / `couponPositionId` | `RemoveAnonymousCoupons` / `VoidAnonymousCoupon` (both without async option) |

**VERIFIED**: `LoyaltyMembershipAssigned` does **not** carry `membershipId`, `programId`, account
balances or coupons. Those live in `PurchaseTransaction.loyalty.loyaltyMemberships[]`
(`P/datatype/loyalty_datatype.proto:75-124`, with `verified`, `anonymous`, `coupons[]`,
`accounts[]{accountBalance}`, `membershipPreferences[]`, `receiptContent`). They can be read only
from `PurchaseTransactionChanged`, `GetPurchaseTransaction` or the final receipt.
**VERIFIED**: there are no "points earned" or "checkout coupon" events. Loyalty results
(earn/burn/checkout coupons) appear only in the receipt (`R/loyalty_datatype.proto:188-202`).
The sample receipt shows 4.00 "Points" earned from promotion `promotion-base-points`, even though
no membership was assigned (the field covers what a customer earned, or would earn as a member, `R/loyalty_datatype.proto:258-260`).

### 1.6 Payment (`payment_session_event.proto`)

These events matter for the sale: `PaymentProcessStarted` (with `paymentSessionSums`),
`CashPaymentPositionCreated` / `Voided`, `EftPaymentPositionCreated` / `Started` / `Completed` /
`Voided`, `CouponPaymentPositionCreated`, `FixedValueVoucherPaymentPositionCreated` / `Voided`,
`PromotionPaymentPositionsCreated` (a pricing "credit" action booked as a payment),
`PaymentProcessCompleted` (with `paymentPositionIds[]`) and `PaymentProcessAborted`. Online,
financing and foreign-currency payment variants also exist.
`PaymentSessionSums{totalToPay, totalPaid, balance, totalCashback, totalRounding, change, totalToPayRounded, balanceRounded}`
are `Money` values (`P/datatype/payment_session_datatype.proto:47-79`).
`CashPaymentPositionCreated` carries `paymentPositionId`, `clientId` (the client location; the
field name is a legacy misnomer), `clientTransactionId` (a client UUID used for idempotency),
`amount` and `paymentTransactionType` (PAYMENT/CHANGE/ROUNDING/CASHBACK).

OBSERVED in the sample: the change (-1.33 EUR) is a *second*, system-generated
`CashPaymentPositionCreated` with `PAYMENT_TRANSACTION_TYPE_CHANGE`, `clientId = location` and
`clientTransactionId = paymentPositionId` (`S/07`).

### 1.7 Fiscal (`fiscal_transaction_event.proto`)

`FiscalTransactionAssigned{fiscalTransactionId}` is OBSERVED (`S/04`), asynchronously after
opening, **without a traceId**. `VoidFiscalInformationAssigned` and `ReturnFiscalInformationAssigned`
exist for voids and returns. The German TSE data (KassenSichV) only reaches the receipt
(`fiscalTransaction.attributes.DE_*`). The sample used a simulator (`"++FCC+SIMULATOR++"`).
Not relevant for the agent, but a faithful simulator should emit `FiscalTransactionAssigned`.

### 1.8 Closing actions (`action_event.proto`)

`ClosingActionsFailed` / `ClosingActionsFinished{closingActionsResultData}`,
`ClosingActionAcknowledged{actionId}` and `ClosingActionRetried{actionId}`. Details in section 6.
None of these occur in the simple sale sample.

### 1.9 Restrictions (`restriction_event.proto`)

`CustomerAgeConfirmed{customerAge}`, `HazardousRestrictionConfirmed{articleId}` and
`SalesRestrictionForReturnArticleConfirmed{articleId}` are answers to the `Restriction` oneof on an
`ArticlePosition` (`CustomerAgeRestriction{minimalAge}`, `HazardousRestriction`, `SalesRestriction`,
`P/datatype/restriction_datatype.proto`). A restricted article (alcohol, 18+) forces a
`ConfirmCustomerAge` before payment (**ASSUMPTION** about enforcement). **Avoid such articles at the booth.**

### 1.10 Mesh (`mesh_*.proto`)

**VERIFIED** (`P/command/mesh_command.proto`, `P/event/mesh_event.proto`, `P/datatype/mesh_enum.proto`).
Till mesh commands that let a till claim a purchase transaction: `ClaimPurchaseTransaction`,
`ForceClaimPurchaseTransaction`, `LockPurchaseTransaction` and `UnlockPurchaseTransaction`, all
with `location`, `cashdrawer_id`, `employee_id` of the claiming till. Events are
`PurchaseTransactionClaimed`, `...ForceClaimed`, `...Locked`, `...Unlocked`, `...Anchored` (with
the definitive `receiptNumber`; a permanent receipt number is assigned here when needed) and
`PurchaseTransactionMeshCacheUpdated{meshPurchaseTransactionStates[]}`. The states are
`MESH_PURCHASE_TRANSACTION_STATUS_{AVAILABLE,LOCKED,ANCHORED}`. The use case is to start a basket
on one device (mobile pre-scan, line busting, service counter) and finish it on another till.
Not needed for the showcase.

### 1.11 Out of scope for the showcase (exists, skip in the simulator)

Deposit refund (Pfand: `DepositRefund*`), service counter receipts (`ServiceCounterReceipt*`),
financial transactions (gift card / voucher **sale**: `FinancialTransactionPosition*`,
`VoucherRedemptionPosition*`), pay-in/pay-out, accounts receivable, marketplace facilitator
(Instacart/Uber, `MarketplaceFacilitator*`). Note: selling a gift card is what drives the
`IN_CHARGING_FINANCIAL_TRANSACTION` status. The sample passes through it even without such a
position (OBSERVED `S/09`).

---

## 2. Lifecycle state machine and finality rule

### 2.1 Status enum

**VERIFIED** (`P/datatype/purchase_transaction_enum.proto:21-55`): `PurchaseTransactionStatus` is
UNSPECIFIED=0, CREATED=1, OPEN=2, IN_PAYMENT=3, CLOSED=4, IN_CLOSING=5, CANCELLED=6,
IN_CANCELLATION=7, SUSPENDED=8, IN_SUSPENSION=9, IN_CHARGING_FINANCIAL_TRANSACTION=10.
`PurchaseTransactionType`: SALE, VOID, GOODS, PAY_IN, PAY_OUT, PAYMENT_EXCHANGE, DEPOSIT_VOUCHER (`:60-85`).

### 2.2 Transitions

```text
CreatePurchaseTransaction
        |
        v
   [CREATED] --AddArticle (1st)--> [OPEN] <-------------------------------+
                                     |  AddArticle / ItemCount / Void /    |
                                     |  discounts / loyalty / customer     |
                                     |  (status stays OPEN)                |
                                     |                                     |
                     StartPaymentProcess                    AbortPaymentProcess
                                     v                                     |
                                [IN_PAYMENT] --------------------------------+
                                     |  payments until balance = 0
                                     |  -> PaymentProcessCompleted (still IN_PAYMENT)
                                     v   (automatic, no close command)
              [IN_CHARGING_FINANCIAL_TRANSACTION]   (gift cards charged, if any)
                                     v
                               [IN_CLOSING]   closing actions; failed ones ->
                                     |        Acknowledge/RetryClosingAction (ASSUMPTION: blocks here)
                                     v
                                [CLOSED]  => PurchaseTransactionClosed (+ Finalized)    FINAL, SOLD

  OPEN/IN_PAYMENT --CancelPurchaseTransaction--> [IN_CANCELLATION] --> [CANCELLED]   FINAL, NOT SOLD
  OPEN           --SuspendPurchaseTransaction--> [IN_SUSPENSION]  --> [SUSPENDED]    FINAL for this id
                    ResumePurchaseTransaction(receipt_id) -> NEW transaction id (receipt_reference RESUME)
  CLOSED receipt --VoidPurchaseTransaction(receipt_id)    -> NEW transaction of type VOID (reverses sale)
  CANCELLED rcpt --RecoverPurchaseTransaction(receipt_id) -> NEW transaction (PurchaseTransactionRecovered)
```

What is observed and what is derived:

- OBSERVED in the sample: CREATED -> OPEN on the first `AddArticle` (`S/02` and `S/03` share
  one traceId, the add-article test step), OPEN -> IN_PAYMENT (`S/05`), and the automatic chain
  after the covering cash payment (`S/06`..`S/11` all share the traceId of the payment test step).
- DERIVED from proto comments: cancel, suspend, resume, void and recover. `GetNotClosedPurchaseTransactions`
  defines "not closed" as anything except CLOSED, SUSPENDED and CANCELLED
  (`P/query/purchase_transaction_query.proto:31-39`). Those three are the terminal statuses.
- **ASSUMPTION**: whether CANCEL is allowed from IN_PAYMENT, and whether failed closing actions
  hold the transaction in IN_CLOSING until they are acknowledged.

### 2.3 Finality rule (what the agent may treat as "sold")

| Class | Events | Meaning for analytics/agent |
|---|---|---|
| Provisional (mutable phase) | Created, Opened, PositionAdded, ArticlePositions*, ItemCountChanged, Voided/Unvoided, PriceOverridden, *DiscountApplied/Removed, PromotionApplied/Removed, Customer*, Loyalty*, AnonymousCoupon*, SubTotalPositionAdded, FiscalTransactionAssigned, PaymentProcess*, *PaymentPosition*, InCharging..., InClosing, InCancellation, InSuspension, ClosingActions*, ExtensionPropertiesAdded, Changed (non-final) | "Intent / live basket". Perfect for live UX and in-basket offers. **Never** count as sales. |
| Final: sold | `PurchaseTransactionClosed` (and `Finalized` with status CLOSED) | Count only receipt positions with `revenuePosition.effectual = true`. Line-voided positions are `effectual=false, manuallyVoided=true` (`R/basket_datatype.proto:105-114`). Return positions are negative. |
| Final: not sold | `PurchaseTransactionCancelled` (Finalized CANCELLED) | Discard provisional state. The CanceledReceipt may carry `recovery_data`. |
| Final for this id, maybe later | `PurchaseTransactionSuspended` | Not sold. If resumed, the sale arrives under a **new** purchaseTransactionId with `receiptReference{type RESUME}`. |
| Later correction | a closed transaction of type VOID, a later return (`ReturnArticleFromReceipt`) | Reverses an earlier sale: subtract it. |

Practical rule for the showcase:

- **Sales velocity** ("article X sells poorly") comes from closed receipts only, plus a seeded
  history.
- **Live insights** (basket context, shopper behaviour) come from provisional events, and the UI
  labels them "provisional".
- The **checkout voucher** is triggered by `PurchaseTransactionClosed`. That event already
  contains the whole receipt, so the workflow does not need to "wait" or join state.

---

## 3. Exact data shapes

### 3.1 Money and decimals (two different encodings)

- Purchase API: `BDecimal{scale:int32, int_val:int64}` and `Money{currency (ISO-3), amount: BDecimal}`
  (`P/datatype/common_datatype.proto:37-57`). The value is `intVal / 10^scale`.
  In proto3 JSON, `intVal` is a **string** (int64), and a zero value omits `intVal`:
  `{"scale": 2}` means 0.00. OBSERVED: 8.67 EUR is `{"scale":2,"intVal":"867"}`, the change is
  `{"scale":2,"intVal":"-133"}`, and the client's 10 EUR cash is `{"intVal":"10"}`, i.e. scale 0
  (`S/06`). **Scale varies per value, so always normalise.** Tax rate 19 % is
  `{"scale":2,"intVal":"1900"}` (19.00, a percent number, not 0.19).
- Receipt API: `de.gebit.rp.protobuf.basic.Decimal{value: string}`, for example
  `{"value":"8.67"}` (`simpleSale.json`).
- **Percent convention is ambiguous.** Tax rate is 19.00 (percent), while
  `PaymentSurcharge.surcharge_rate` is a fraction where 0.005 means 0.5 %
  (`P/datatype/payment_session_datatype.proto:575-576`). The convention for
  `ApplyPercentageArticlePositionDiscount.percentage_discount` is not documented. Ask GEBIT. My
  examples assume percent (20.00).

### 3.2 Identifiers

Example values come from our simulator (seed and generated UUIDs), not from GEBIT's sample.

| Field | Example value (our simulator) | Notes |
|---|---|---|
| `purchaseTransactionId` | `0d9c6e25-1b15-42df-bed2-5baeebb4f839` | UUID, returned synchronously by `CreatePurchaseTransaction`. Equals `Receipt.receiptId`. |
| `positionId` | `c98b3473-2a58-40f7-a214-417a9089662e` | UUID, **only learned from `PositionAdded`**. |
| `articleId` | `ID100001` | Technical master-data id (GEBIT's sample uses the same `ID` + article number pattern). `AddArticle` takes **article_id**, not the EAN. |
| `articleNumber` | `100001` | Business article number (Artikelnummer). |
| EAN / PLU | (`capturingInformation.inputType/inputValue`) | The input type is an EAN, a PLU or an article number; `inputMethod` tells scan, manual entry, fixed key, item repeat and generated input apart (`P/datatype/basket_datatype.proto:274-292`). |
| `receiptNumber` | `10101270216000042` | Assigned at opening (`PurchaseTransactionOpened`). GEBIT's numbers are longer (29 digits, see below). |
| `paymentPositionId`, `fiscalTransactionId`, `membershipPositionId`, `couponPositionId` | UUIDs | |
| `clientTransactionId` | client UUID | Idempotency key for payments; the client (MCO, MMCO or MSCO) creates it. |

**ASSUMPTION** (pattern fits GEBIT's sample, confirm with GEBIT): GEBIT's 29-digit receipt number
decomposes as `<2-digit prefix> | <ISO 3166 numeric country, 276 = DE> | <company> | <store> | <till> | <2 digits> | <yyMMdd, matches createdAt> | <8-digit sequence>`.
Our simulator uses the shorter `<store><till><yyMMdd><6-digit sequence>`
(`app/gposdemo/pos/receipt.py`), for example `10101270216000042` for sequence 42 on 2027-02-16.
**ASSUMPTION**: the client must resolve EAN to `articleId` before calling `AddArticle`. Ask whether
`article_id` may be an EAN in the lab's master data.

### 3.3 Who and where: store / workstation / operator

- `location`: OBSERVED `"Root.DE.999.101.01"` (our simulator's booth till uses the same value),
  mandatory on `CreatePurchaseTransaction`. The same
  string is the TSE `DE_SerialNoTill` ("Seriennummer Kasse") in the receipt, so **location
  identifies the till/workstation**. **ASSUMPTION**: the hierarchy is
  Root.<country>.<company>.<store>.<till>, with the store at `Root.DE.999.101`.
- `cashdrawerId` (GEBIT's sample uses a test cash-drawer name; our simulator sends the till id,
  `"01"`), `employeeId` (a technical id; GEBIT's sample puts `ID` in front of the employee number,
  which the receipt also shows as `employeeNumber`; our simulator sends `"booth"`),
  `employeeSessionId`, and `applicationMode` (for example MCO, SCO attendant or bakery; it selects
  the configuration in COMPAS).
- Command `header.originator.identity_id` (the employee id rather than the employee number) and the
  optional `header.approver` (`P/command/common_command.proto:22-46`).
- **VERIFIED**: only `PurchaseTransactionCreated`, `PurchaseTransactionRecovered` and the mesh
  events carry `location`. Every other event has only `purchaseTransactionId`. A consumer or bridge
  that wants store/till routing must keep a `txId -> location` cache (Created is always offset 1).

### 3.4 Timestamps (again two encodings)

- Purchase API: GEBIT's own `datatype.Timestamp{seconds:int64, nanos}` and
  `OffsetTimestamp{seconds, nanos, offset (minutes)}` (`P/datatype/common_datatype.proto:161-198`).
  The JSON is an object such as `{"seconds":"1802784001","nanos":412000000,"offset":60}`, **not**
  an RFC 3339 string, because it is a copy and not `google.protobuf.Timestamp`.
- Receipt API: `OffsetTimestamp{timestamp: google.protobuf.Timestamp, offset: sint32}`, so the
  JSON is `{"timestamp":"2027-02-16T13:20:01.412Z","offset":60}` (same instant; our simulator's
  values, GEBIT's sample carries nanosecond precision).
- OBSERVED: `header.eventTimestamp` of `S/06`..`S/11` is the same instant, to within a
  millisecond, for all six, while `metadata.creationTimestamp` spreads over about a third of a
  second. The events are mapped and published as a batch after the command finishes. **Use `metadata.creationTimestamp` as the business time and
  `metadata.offset` for order.**

### 3.5 `metadata.offset` and `traceId`

- `offset` is a per-transaction version counter. OBSERVED values run 1..11 for the one
  transaction; per the doc it only ever grows and counts the versions of the current
  state (`P/event/purchase_transaction_event.proto:45-47`). Use it for dedup, gap
  detection and re-ordering. A good dedup key is `purchaseTransactionId + ":" + offset`.
- `traceId` is copied from the command header. OBSERVED: the test step names become trace ids, and
  every event caused by one command shares it. Events not caused by a command
  (`FiscalTransactionAssigned`) have none. **For the showcase, set `trace_id` to our scan or
  proposal id.** It then comes back on every resulting event: a free correlation key.

### 3.6 `pricingInformation`

`PricingInformation{totalSum, netTotalSum, taxSums[], setDiscounts[], articlePositions[]{positionId, calculatedPositionPrice{basePrice, baseValue, effectiveValue, taxes[], pricePerUnit, extensionProperties}, positionDiscounts[]{baseDiscount{discountId, discountType ABSOLUTE|RELATIVE|NEW_PRICE, description, amount, percentage, reasonCode, extensionProperties}, setDiscountId}, basketRoundingFractionDiscount}, pricingMode, voucher/payment/... positions, basketRoundingDiscount}`
(`P/datatype/purchase_transaction_datatype.proto:179-235`, `P/datatype/basket_datatype.proto:144-212`).

- `basePrice` is the price per item, `baseValue` the position value before discounts, and
  `effectiveValue` the value after discounts (`P/datatype/common_datatype.proto:62-86`).
- OBSERVED: pricing adds `extensionProperties [{key:"positionType", stringValue:"articlePosition"}]`
  to each calculated position price.
- **ASSUMPTION**: `pricingInformation` on each event is the recalculated **whole basket**, since
  `totalSum` is the basket total. That means `articlePositions[]` lists all positions, because a
  promotion can re-price other lines. The payload therefore grows O(n) with basket size. The sample
  has only one line, so this cannot be proven from it.
- **VERIFIED**: the "Mandatory" comments are not reliable. `PurchaseTransactionOpened`,
  `PaymentProcessCompleted`, the change `CashPaymentPositionCreated`, `InCharging` and `InClosing`
  come **without** `pricingInformation` (`S/02`,`S/07`-`S/10`). `PaymentProcessCompleted` also
  lacks the "Mandatory" `paymentPositionIds`, and `paymentSessionSums` lacks
  `totalToPayRounded/balanceRounded`. Consumers must treat everything as optional.

### 3.7 `extensionProperties` (can we carry an offer or proposal id? Yes)

`Property{key, typedValue: oneof{stringValue, integerValue(sint64), decimalValue(BDecimal), boolValue, timestampValue, offsetTimestampValue, dateValue, timeValue, dateTimeValue, bytesValue, moneyValue, jsonValue}}`
(`P/datatype/common_datatype.proto:293-351`). Almost every command has `extension_properties`.
OBSERVED propagation:

- `CreatePurchaseTransaction` ext `foo=bar, baz=42` appears on `PurchaseTransactionCreated` and as
  the **receipt-level** `extensionProperties`.
- `AddArticle` ext `john=doe, baz=23` appears on `PurchaseTransactionOpened`, `PositionAdded` and
  `FiscalTransactionAssigned`, and is **persisted on the receipt position**
  (`basket.receiptPositions[0].extensionProperties`) and on `fiscalTransaction.extensionProperties`.
- `AddExtensionProperties(bearerType PURCHASE_TRANSACTION|ARTICLE_POSITION|PAYMENT_SESSION|PAYMENT_POSITION, bearerId, props)`
  attaches properties later (`P/command/purchase_transaction_command.proto:470-490`) and emits
  `ExtensionPropertiesAdded`.

This gives a clean way to stamp `showcase.proposalId`, `showcase.offerId` or `showcase.scanId` on
a line or the receipt and find it again in the final receipt (for example "this sale used price
proposal P-0042"). **ASSUMPTION**: GEBIT allows arbitrary keys. A key namespace such as
`showcase.*` is advisable.

### 3.8 `google.protobuf.Any` / `@type` JSON mapping

The sample files use the proto3 JSON mapping for `Any`:
`{"@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.<Event>", ...fields...}`.
Field names are lowerCamelCase, enums are names, int64 values are strings, default values are
omitted, and bytes are base64. The **receipt inside `Closed`/`Cancelled`/`Suspended`/`Finalized`
stays binary** (`serializedReceiptFormat:"PROTOBUF"`, bytes, base64 in JSON) and is itself an
`Any`. A JSON-only consumer still needs the receipt descriptor to read it. **VERIFIED** by
decoding it (see the header of this report).

---

## 4. POS simulator: commands and command -> event sequences

### 4.1 Minimal command set (booth scenario)

| # | Command (RPC) | Returns | Why |
|---|---|---|---|
| 1 | `CreatePurchaseTransaction{header, location, employee_id, cashdrawer_id, extension_properties, application_mode}` | `PurchaseTransactionId` | new basket per visitor |
| 2 | `AddArticle{header, purchase_transaction_id, article_id, item_count, extension_properties, capturing_information, [supplied_price_information], [captured_promotion]}` | Empty | every scan |
| 3 | `ChangeArticlePositionItemCount{position_id, item_count}` | Empty | "x2" key |
| 4 | `VoidArticlePosition{position_id}` | Empty | Zeilenstorno |
| 5 | `StartPaymentProcess{purchase_transaction_id}` | Empty | "Summe" |
| 6 | `CreateCashPayment{amount: Money, client_id, client_transaction_id}` (or `CreateEftPayment`) | Empty | closing is automatic at balance 0 |
| 7 | `CancelPurchaseTransaction{cancellation_reason, cancellation_reason_code}` | Empty | abandoned basket |
| 8 | `AssignLoyaltyMembership{membership_identification_value, capturing_information}` | Empty | "Kundenkarte" scan, personalisation |
| 9 | `GetPurchaseTransaction{purchase_transaction_id}` (query) | `PurchaseTransaction` | UI and agent read full basket state |

### 4.2 Nice-to-have

- `ApplyPercentageArticlePositionDiscount`, `ApplyAbsoluteArticlePositionDiscount`,
  `OverrideArticlePositionPrice`: an employee applies an AI-suggested in-basket discount with
  `header.approver`.
- `ApplyArticlePositionPromotion{captured_promotion.promotion_code}`: a "digital discount sticker".
- `ApplyAnonymousCoupon{prefix, promotion_code}` / `AssignLoyaltyCoupon{coupon_identification_value}`:
  redeem the next-visit voucher.
- `AddExtensionProperties` (stamp a proposal id), `AbortPaymentProcess`,
  `ApplyPercentage/AbsoluteBasketDiscount`, `AssignCustomer`, `SuspendPurchaseTransaction` /
  `ResumePurchaseTransaction`, and `VoidPurchaseTransaction` (Bonstorno, to show finality).
- Errors follow the gRPC rich error model: `ErrorMessage{error_code, error_message, error_details[{key,value}], trace_id}`
  (`P/datatype/common_datatype.proto:200-234`). The simulator should reject, for example, a discount
  on a non-discountable line (`ArticlePosition.is_manually_discountable`,
  `P/datatype/basket_datatype.proto:102-104`) or a second requested manual basket discount
  (a basket accepts at most one requested manual discount, `P/command/basket_command.proto:379`).

### 4.3 Sequences

Status in brackets. Source: **O** = observed in the GEBIT sample, **D** = derived from proto
comments/fields, **A** = assumption.

| Scenario | Command(s) | Resulting events (in order) | Src |
|---|---|---|---|
| New basket | CreatePurchaseTransaction | PurchaseTransactionCreated [CREATED] (offset 1) | O |
| First scan | AddArticle | PurchaseTransactionOpened [OPEN, receiptNumber] -> PositionAdded [OPEN] -> FiscalTransactionAssigned (async, no traceId) | O |
| Next scan | AddArticle | PositionAdded (new positionId) | D |
| Same article again | AddArticle (same article_id) | PositionAdded with a **new** positionId (no merge documented); alternatively the POS sends ChangeArticlePositionItemCount -> ArticlePositionItemCountChanged{itemCount: new absolute count} | D (merge config: A) |
| Quantity change | ChangeArticlePositionItemCount{position_id, item_count} | ArticlePositionItemCountChanged{positionId, itemCount, pricingInformation} | D |
| Line void | VoidArticlePosition{position_id} | ArticlePositionVoided{positionId, pricingInformation}; position `voided=true`; receipt `effectual=false, manuallyVoided=true` | D |
| % line discount | ApplyPercentageArticlePositionDiscount{position_id, percentage_discount, reason, reason_code} | PercentageArticlePositionDiscountApplied{...}; pricing shows positionDiscounts[] RELATIVE; `requested_manual_discount.percentage_discount` set | D |
| Absolute line discount | ApplyAbsoluteArticlePositionDiscount{absolute_discount (per item)} | AbsoluteArticlePositionDiscountApplied | D |
| New price for the line | OverrideArticlePositionPrice{price_override_information.new_price (per item)} | ArticlePositionPriceOverridden{newPrice, reason, reasonCode}; discount type NEW_PRICE | D |
| Basket discount | ApplyPercentageBasketDiscount / ApplyAbsoluteBasketDiscount | Percentage/AbsoluteBasketDiscountApplied; pricing shows setDiscounts[] referencing derived positionDiscounts | D (set mapping: A) |
| Discount sticker | ApplyArticlePositionPromotion{captured_promotion.promotion_code} (or AddArticle.captured_promotion) | ArticlePositionPromotionApplied{capturedPromotion} | D |
| Customer card | AssignLoyaltyMembership{membership_identification_value} | LoyaltyMembershipAssigned{membershipPositionId, pricingInformation (re-priced)} (+ maybe LoyaltyCouponAssigned for coupons from the membership) | D (+A) |
| Coupon scan | AssignLoyaltyCoupon | LoyaltyCouponAssigned or UnverifiedLoyaltyCouponAssigned (no membership yet) | D |
| Anonymous coupon | ApplyAnonymousCoupon{prefix, promotion_code} | AnonymousCouponApplied{couponPositionId} | D |
| Customer | AssignCustomer{customer: CustomerData} | CustomerAssigned{customer} | D |
| Payment start | StartPaymentProcess | PaymentProcessStarted [IN_PAYMENT, paymentSessionSums] | O |
| Cash payment with change | CreateCashPayment{amount 10 EUR} | CashPaymentPositionCreated (PAYMENT, 10) -> CashPaymentPositionCreated (CHANGE, -1.33) -> PaymentProcessCompleted [IN_PAYMENT] -> PurchaseTransactionInChargingFinancialTransaction -> PurchaseTransactionInClosing -> PurchaseTransactionClosed [CLOSED, receipt] | O |
| Payment abort | AbortPaymentProcess | PaymentProcessAborted -> back to OPEN | D/A |
| Cancel basket | CancelPurchaseTransaction{reason} | PurchaseTransactionInCancellation [IN_CANCELLATION] -> PurchaseTransactionCancelled [CANCELLED, CanceledReceipt] | D |
| Park basket | SuspendPurchaseTransaction | PurchaseTransactionInSuspension -> PurchaseTransactionSuspended [SUSPENDED] | D |
| Low-granularity (if enabled) | any | PurchaseTransactionChanged after state changes (coalescing allowed); at the end PurchaseTransactionFinalized then the final Changed | D |

**ASSUMPTION** to check with GEBIT: selling a deposit article (Pfand) may produce a second
`PositionAdded` (DEPOSIT_SALE with `referenced_position_id`) for one `AddArticle`. Keep booth
articles deposit-free and age-restriction-free.

Event volume for a booth basket (3 articles, loyalty card, card payment): about 13-15 events.
Routing **every** event to an LLM workflow (14-20 s and real tokens each, 50 USD LiteLLM budget)
would be wasteful. Subscribe SAM to `PositionAdded`, `LoyaltyMembershipAssigned` and
`PurchaseTransactionClosed` only. The topic taxonomy in section 7 makes that a subscription choice.

---

## 5. Promotions and AI-driven prices: how they are represented, and what is realistic

### 5.1 What the API offers

| Mechanism | Command / data | Semantics in the API | Fit for the showcase |
|---|---|---|---|
| Master-data price | (outside the Purchase API) | `AddArticle` uses the master-data price unless supplied; `SuppliedPriceInformation{base_price, source, price_per_unit, tax_class}` feeds the price calculation, and without it the master-data unit price applies (`P/datatype/basket_datatype.proto:214-233`). Receipt `ArticlePosition.price_source` records where the price came from, by default the article master data (`R/basket_datatype.proto:272-274`). Sample `priceSource: "freezePrice"` | **Primary path for markdowns (Preisreduzierung)**: AI -> approval -> price change at article master/price service -> next scan picks it up -> ESL shows it |
| Promotion engine | `CapturedPromotion{promotion_code}`, a code the pricing/promotion service knows (`P/datatype/basket_datatype.proto:417-424`); results as `positionDiscounts[]` / `setDiscounts[]`; receipt `BaseDiscount.promotion_id` (`R/basket_datatype.proto:731`); `PromotionActionTrigger{promotion_id, oneof anonymous_coupon / loyalty_membership / unqualified}` (`P/datatype/common_datatype.proto:112-159`); `PromotionPaymentPosition` (credit as payment) | Promotions are defined in GEBIT's promotion service and applied automatically during basket calculation | **Primary path for "Aktion"** (time-boxed, reversible, shows regular price plus discount on the receipt) |
| Discount sticker | `ApplyArticlePositionPromotion` / `AddArticle.captured_promotion` | POS captures a promotion code for a line, for example from a discount sticker | Digital sticker: the AI-approved offer becomes a promotion code applied to the visitor's line |
| Requested manual discount | `OverrideArticlePositionPrice`, `Apply{Percentage,Absolute}ArticlePositionDiscount`, `Apply{Percentage,Absolute}BasketDiscount` (the service names these requested manual discounts, `P/service/purchase_transaction_service.proto:135-150`); only one per line (oneof) and one per basket; only if `is_manually_discountable` | Cashier-initiated, reason + reason_code, optional `header.approver` -> `approvals[]` | Employee one-click "apply the AI suggestion now" at the till, for example for a damaged item or best-before date (MHD) |
| Loyalty / coupons | `AssignLoyaltyMembership`, `AssignLoyaltyCoupon`, `ApplyAnonymousCoupon`; `LoyaltyCoupon.from_membership` (true when the coupon came in with the membership) | Personalised offers come via membership coupons | **Next-visit voucher redemption**, personalised in-basket offer |

Public context (GEBIT marketing): the platform is described as a "reactive, event-based
microservice architecture" with a **Price and Promotion Calculation Service** ("price-lookup
capabilities and what-if scenarios"), a **Promotion Service** ("stores promotion definitions ...
importing promotions from third-party systems"), a **Dynamic Pricing** option and connectors to
third-party loyalty programmes. These quotes come from search-result snippets; the page returned
404 when fetched today, so treat them as marketing context, not API facts.

### 5.2 What is most realistic for "the AI-approved price applies at the next scan"

1. The agent detects a slow seller from closed receipts, stock and promotions. It proposes either a
   markdown (new regular price in master data) or an Aktion (promotion definition, for example -20
   % on article 100001 at store 101 until 18:00).
2. An employee approves on the tablet. Our side records the approver as a GEBIT-style
   `AuthorizationInformation{identity_id}`.
3. The result is sent as a **price change event / command to the article master / price service**
   (format promised by GEBIT; interim proposal in section 8.7) or as a **promotion** to the
   promotion service. ESL gets the same event (label update).
4. The next `AddArticle` of that article returns a `PositionAdded` with the new `basePrice`
   (markdown) or with `positionDiscounts[]` (promotion). The monitor shows the price changing
   "live at the next scan".
5. Positions already in a basket keep their price. **ASSUMPTION**: `priceSource "freezePrice"`
   suggests the price is frozen when the line is added, so the change is honest: it applies "from
   the next scan".

Not recommended as the main story: having the agent push `OverrideArticlePositionPrice` or
discounts into running transactions. Those are cashier commands, and a backend issuing them would
look like the AI acting alone. Use them only for the explicit "employee applies it at the till
with approver" variant.

In the simulator, the stand-in for GEBIT pricing is a tiny pricing stub: article master price table
+ promotion table, read at `AddArticle`. Swapping to the lab means deleting the stub. The simulator
should never put `supplied_price_information` on normal scans; that field is for barcode-embedded
prices.

Legal remark (general knowledge, not from GEBIT docs): German PAngV section 11 (EU Omnibus) requires
a price-reduction announcement to state the lowest price of the previous 30 days. An ESL or monitor
showing "reduziert" should display it. The agent can compute it from price history, which adds
credibility on a German trade-show floor.

---

## 6. Closing actions and a voucher on the receipt

- **VERIFIED** (`P/datatype/action_datatype.proto:20-57`, `P/command/action_command.proto:21-46`,
  `P/event/action_event.proto:25-135`): `ClosingActionsResultData{failed_action_results[]{action_id, is_retryable, number_of_retries, error_message}, finished_action_results[]{action_id}, extension_properties}`.
  It lives on `PurchaseTransaction.closing_actions_result_data` (field 35). `ClosingActionsFailed`
  and `ClosingActionsFinished` report it, and the client must explicitly call
  `AcknowledgeClosingAction{action_id}` or `RetryClosingAction{action_id}`, which emit
  `ClosingActionAcknowledged` / `ClosingActionRetried`.
- **VERIFIED**: there is **no** command or field to register an external closing action. The
  action ids and types are internal and not enumerated in the API. **ASSUMPTION**: these are
  GEBIT-configured steps such as loyalty purchase reporting
  (`LoyaltyPurchaseResult.deferred_purchase_report_request`: a request for the loyalty system
  that goes out once the purchase transaction is closed, `R/loyalty_datatype.proto:199-201`), eReceipt,
  or financial-transaction charging. The sample shows no closing-action events, so none were
  configured or none were emitted.
- **Conclusion**: an external voucher service cannot hook into closing through the public Purchase
  API. Participation before closing would happen *inside* the GEBIT platform (promotion engine or
  loyalty connector) and would surface in the receipt.
- **The receipt can carry a voucher natively.** `Receipt.loyalty.loyaltyPurchaseResult.checkoutCoupons[]`
  = `CheckoutCoupon{application{program{id,name}, membershipId, benefitId, promotionId, reported, extensionProperties}, couponId, printContent: FormattedContent}`.
  `FormattedContent.lines[]` supports text with font size/style, images and barcodes including
  `SYMBOLOGY_QRCODE` (descriptor dump of `formatted_content.proto`). `earnedAmounts` and
  `burnedAmounts` sit next to it (the sample earned 4.00 Points). A validated example is in 8.6.
- **Showcase recommendation**:
  - Simulated: the simulator's "loyalty stub" can put a `CheckoutCoupon` into the receipt at
    closing, which is faithful to GEBIT's model. The workflow triggered by
    `PurchaseTransactionClosed` reads it, or issues the voucher itself after closing and shows a QR
    on the monitor or tablet.
  - Live in the GEBIT lab: ask GEBIT whether their promotion engine can grant a checkout-coupon
    benefit for a promotion we define. If not, the after-close path is the honest one: the voucher
    is a digital coupon, redeemed next visit via `ApplyAnonymousCoupon{prefix, promotion_code}` or
    `AssignLoyaltyCoupon`.

---

## 7. Topic taxonomy on Solace, and proto vs JSON on the wire

### 7.1 Raw GEBIT events (one topic per event, mechanically derived)

```text
gebit/rp/purchase/v2/{category}/{EventName}/{country}/{company}/{store}/{till}/{purchaseTransactionId}

category  = proto file stem of the event (basket, purchase_transaction, payment_session, loyalty,
            customer, fiscal_transaction, action, restriction, sub_total, mesh, ...)
EventName = message name (PositionAdded, PurchaseTransactionClosed, ...)
location  = "Root.DE.999.101.01" -> DE/999/101/01   (from PurchaseTransactionCreated, cached per txId)
```

Examples:

- `gebit/rp/purchase/v2/basket/PositionAdded/DE/999/101/01/5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60`
- `gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionClosed/DE/999/101/01/5b1f0c2e-...`
- `gebit/rp/purchase/v2/loyalty/LoyaltyMembershipAssigned/DE/999/101/01/5b1f0c2e-...`

Useful subscriptions:

- Every scan, all stores: `gebit/rp/purchase/v2/basket/PositionAdded/>`
- Final sales of store 101: `gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionClosed/DE/999/101/>`
- Not sold: `gebit/rp/purchase/v2/purchase_transaction/PurchaseTransactionCancelled/>`
- Everything for one basket (monitor drill-down): `gebit/rp/purchase/v2/*/*/*/*/*/*/5b1f0c2e-...`
- Everything at the booth till: `gebit/rp/purchase/v2/*/*/DE/999/101/01/>`

Message properties:

- Solace user properties: `eventType` (full proto name), `purchaseTransactionId`, `offset`,
  `traceId`, `location`, `apiVersion=purchase-2.50.0`.
- Application message id `{txId}:{offset}` for dedup. Content type `application/json`, or
  `application/x-protobuf` for binary.
- Use a partitioned queue with partition key = `purchaseTransactionId` where per-basket order
  matters (Solace keeps publisher order per flow; the key keeps a basket on one consumer).
- Why the prefix comes from the proto package (`de.gebit.rp.purchase.purchase.v2`): the bridge in
  GEBIT's lab can derive the topic from the message descriptor alone, so simulator and lab produce
  identical topics.

### 7.2 Showcase-side topics (ours, not GEBIT's)

- `showcase/pos/v1/scan/{store}/{till}/{articleNumber}`: digest of PositionAdded and
  ItemCountChanged, about 300 bytes, decimals as numbers, `final:false`.
- `showcase/pos/v1/receipt/{store}/{till}/{txId}`: decoded and flattened final receipt (positions
  with `effectual`, totals, loyalty, approvals, extension properties), `final:true`.
- `showcase/pricing/v1/proposal/{created|approved|rejected|expired}/{store}/{articleId}/{proposalId}`:
  agent proposals and tablet decisions.
- `gebit/rp/masterdata/v1/article/PriceChangeRequested/{country}/{company}/{store}/{articleId}`:
  interim emulation of the price-change event GEBIT will specify. Rename to their contract later.
- `showcase/esl/v1/label/update/{store}/{articleId}`: ESL label update.
- `showcase/loyalty/v1/voucher/{issued|redeemed}/{store}/{txId}`: next-visit voucher.
- SAM output topics as in the BSG pattern (`.../results`, `.../errors`).

Broker note (lab, from memory notes): MQTT 1883 is only on VPN `default`. If the POS simulator or
the ESL emulator speaks MQTT, publish on `default` and let the SAM event-mesh entrypoint read there
(as `bsg-desk-events` does).

### 7.3 Proto vs JSON on the wire

| Option | Pro | Contra |
|---|---|---|
| Binary protobuf (what GEBIT services natively use, **ASSUMPTION**) | compact: the sample sale is 6.6 KB of binary events vs 16.6 KB as JSON (measured, `decode_gebit.py`); schema-safe | Not readable on the monitor, Event Portal or in an LLM. **The SAM entrypoint `messageFormat: protobuf` has no descriptor/type setting** (`sam config schema show entrypoint --type event_mesh`, line 32), so it cannot produce named fields (ASSUMPTION that it then passes opaque bytes) |
| Proto3 canonical JSON with `@type` (GEBIT's own sample format) | identical to the GEBIT samples; validates against their descriptors; SAM `messageFormat: json` works; human-readable | receipt still binary (base64) inside; verbose BDecimal/Timestamp objects; `pricingInformation` repeated in every event |
| Digest JSON (ours) | small, LLM-friendly, ASCII-only, below the MCP 2048-byte artifact threshold | a derived contract to maintain |

Recommendation:

- Raw topics carry **canonical proto3 JSON**. The simulator produces it by building real messages
  from GEBIT's descriptor set and serialising with `json_format`, so it cannot drift from the
  schema.
- In GEBIT's lab, a thin bridge maps their async channel (unknown transport: ask) to the same
  topics. If they deliver binary, the bridge converts with the same descriptor set; the decode
  script already proves that works.
- One **digest** step (deterministic code, not an LLM) feeds SAM. It also decodes the receipt
  bytes and strips non-ASCII. The sample store address contains "Düsseldorf", and the memory notes
  record that non-ASCII arrives mangled at solclientjs consumers.

---

## 8. Realistic JSON examples (shortened)

All examples are our own; none is a copy of a GEBIT sample. Examples 8.1 to 8.6 validate against
the GEBIT descriptor sets, and 8.5 was generated with our POS simulator code. Example 8.7 is my own
proposal and is not a GEBIT schema. The ids and dates are illustrative. Location, article and
prices follow our simulator seed: booth till `Root.DE.999.101.01`, article `100001`
"GEBIT Ente (Quietscheente gelb)" at 9.99 EUR (7.99 EUR after the -20 % booth promotion), 19 %
tax class C.

### 8.1 `PositionAdded` after an approved -20 % promotion (my example, validated)

```json
{
  "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.PositionAdded",
  "header": {"eventTimestamp": {"seconds": "1802770512", "nanos": 412000000}},
  "metadata": {"offset": "3", "creationTimestamp": {"seconds": "1802770512", "nanos": 398000000},
               "traceId": "eurocis-booth.scan.7f3c9a"},
  "purchaseTransactionId": "5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60",
  "positionId": "c0a8017e-3b2d-4e5f-8a9b-1c2d3e4f5a6b",
  "articlePositionType": "ARTICLE_POSITION_TYPE_SALE",
  "articleId": "ID100001", "articleNumber": "100001", "itemCount": 1,
  "description": "GEBIT Ente (Quietscheente gelb)",
  "pricingInformation": {
    "totalSum": {"scale": 2, "intVal": "799"},
    "articlePositions": [{
      "positionId": "c0a8017e-3b2d-4e5f-8a9b-1c2d3e4f5a6b",
      "calculatedPositionPrice": {"basePrice": {"scale": 2, "intVal": "999"},
        "baseValue": {"scale": 2, "intVal": "999"}, "effectiveValue": {"scale": 2, "intVal": "799"}},
      "positionDiscounts": [{"baseDiscount": {"discountId": "PROMO-AI-0042",
        "discountType": "DISCOUNT_TYPE_RELATIVE", "description": "Messe-Aktion -20%",
        "amount": {"scale": 2, "intVal": "200"}, "percentage": {"scale": 2, "intVal": "2000"},
        "reasonCode": "AI_PROPOSAL_APPROVED"}}]}],
    "netTotalSum": {"scale": 2, "intVal": "671"},
    "pricingMode": "PRICING_MODE_GROSS"
  },
  "createdAt": {"seconds": "1802770512", "nanos": 398100000, "offset": 60},
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "EAN", "inputValue": "2099100000018"},
  "extensionProperties": [{"key": "showcase.scanId", "typedValue": {"stringValue": "scan-7f3c9a"}}]
}
```

Shortened: `taxSums` (one entry, class C, rate 19.00, tax 1.28, net 6.71, gross 7.99) is left out.
For a pure **markdown** (master-data price change) the same event would show
`basePrice = baseValue = effectiveValue = 799` and no `positionDiscounts`. **ASSUMPTION**: sign and
semantics of `BaseDiscount.amount` (positive = discounted amount).

### 8.2 `ArticlePositionItemCountChanged` (validated)

```json
{
  "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.ArticlePositionItemCountChanged",
  "metadata": {"offset": "5", "creationTimestamp": {"seconds": "1802770530", "nanos": 95000000},
               "traceId": "eurocis-booth.qty.81aa20"},
  "purchaseTransactionId": "5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60",
  "positionId": "c0a8017e-3b2d-4e5f-8a9b-1c2d3e4f5a6b",
  "itemCount": 2,
  "pricingInformation": {"totalSum": {"scale": 2, "intVal": "1598"},
    "netTotalSum": {"scale": 2, "intVal": "1343"}, "pricingMode": "PRICING_MODE_GROSS"},
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN"
}
```

### 8.3 `PercentageArticlePositionDiscountApplied` (employee applies the AI suggestion at the till, validated)

```json
{
  "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.PercentageArticlePositionDiscountApplied",
  "metadata": {"offset": "6", "traceId": "eurocis-booth.proposal.P-0042"},
  "purchaseTransactionId": "5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60",
  "positionId": "c0a8017e-3b2d-4e5f-8a9b-1c2d3e4f5a6b",
  "percentageDiscount": {"scale": 2, "intVal": "2000"},
  "reason": "KI-Vorschlag freigegeben", "reasonCode": "AI_PROPOSAL_APPROVED",
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
  "extensionProperties": [{"key": "showcase.proposalId", "typedValue": {"stringValue": "P-0042"}}]
}
```

The causing command is `ApplyPercentageArticlePositionDiscount{header{trace_id:"eurocis-booth.proposal.P-0042", originator{identity_id:"booth"}, approver{identity_id:"ID200345"}}, ...}`.
**ASSUMPTION**: the approver then appears in `approvals[]` as
`{approverId:"ID200345", approvedCommand:"ApplyPercentageArticlePositionDiscount"}`.

### 8.4 `LoyaltyMembershipAssigned` (validated)

```json
{
  "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.LoyaltyMembershipAssigned",
  "metadata": {"offset": "4", "traceId": "eurocis-booth.loyalty.c11d"},
  "purchaseTransactionId": "5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60",
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
  "membershipPositionId": "0e4d2b9c-1a2b-4c3d-8e9f-a0b1c2d3e4f5",
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "QR", "inputValue": "MEMBER-000123"}
}
```

Use pseudonymous member ids at the booth and never real visitor data: `CustomerData` can carry
names and addresses.

### 8.5 `PaymentProcessCompleted` then `PurchaseTransactionClosed` (our simulator, shortened)

Generated with our POS simulator code (`app/gposdemo/pos/sim.py`, `Simulator._close`) against the
GEBIT descriptor sets: one duck at the booth price 7.99 EUR on till 01, paid with a 20 EUR note.
The status is still IN_PAYMENT, and there is no `pricingInformation`. Unlike GEBIT's sample, our
simulator fills the "Mandatory" `paymentPositionIds` (payment, then change). Shortened:
`header` (same instant as `creationTimestamp`), `totalToPay` (7.99) and the zero sums `balance`,
`totalCashback` and `totalRounding` (`{"scale": 2}` each) are left out.

```json
{
  "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.PaymentProcessCompleted",
  "metadata": {"offset": "8", "creationTimestamp": {"seconds": "1802784007", "nanos": 391000000},
               "traceId": "kasse-01-6d8dd6d4"},
  "purchaseTransactionId": "0d9c6e25-1b15-42df-bed2-5baeebb4f839",
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_IN_PAYMENT",
  "paymentSessionSums": {"totalPaid": {"currency": "EUR", "amount": {"scale": 2, "intVal": "2000"}},
    "change": {"currency": "EUR", "amount": {"scale": 2, "intVal": "-1201"}}},
  "paymentPositionIds": ["f754a5d3-2b49-4517-bfb3-b322038a9936",
                         "1b5ab145-6a05-45c6-b0a6-2b4b6523822c"]
}
```

Three offsets later the same command closes the basket (offsets 9 and 10 are
`PurchaseTransactionInChargingFinancialTransaction` and `PurchaseTransactionInClosing`):

```json
{
  "@type": "type.googleapis.com/de.gebit.rp.purchase.purchase.v2.event.PurchaseTransactionClosed",
  "metadata": {"offset": "11", "creationTimestamp": {"seconds": "1802784007", "nanos": 405000000},
               "traceId": "kasse-01-6d8dd6d4"},
  "purchaseTransactionId": "0d9c6e25-1b15-42df-bed2-5baeebb4f839",
  "closedAt": {"seconds": "1802784007", "nanos": 404000000, "offset": 60},
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_CLOSED",
  "serializedReceiptFormat": "PROTOBUF",
  "serializedReceiptContent": "...",
  "serializedReceiptVersion": "2.13.0"
}
```

`serializedReceiptContent` (left out) is the base64 of a binary `google.protobuf.Any` that packs a
Receipt API 2.13.0 `Receipt`, in which our simulator sets only the receipt id
(= `purchaseTransactionId`), type `SALE`, `closedReceipt`, receipt number `10101270216000042`,
location, currency and total 7.99 (`app/gposdemo/pos/receipt.py`), while GEBIT's receipt carries
far more (`gebit-receipt-api.md`).

### 8.6 Receipt with a next-visit `CheckoutCoupon` (my example, validated against receipt 2.13.0)

```json
{
  "loyalty": {"loyaltyPurchaseResult": {"checkoutCoupons": [{
    "application": {"program": {"id": "BOOTH-CLUB", "name": "Booth Club"},
      "membershipId": "MEMBER-000123", "benefitId": "NEXT-VISIT-2EUR",
      "promotionId": "promo-ai-next-visit-0042", "reported": true,
      "extensionProperties": [{"key": "showcase.proposalId", "typedValue": {"stringValue": "P-0042"}}]},
    "couponId": "CPN-8F2K-0042",
    "printContent": {"lines": [
      {"alignment": "ALIGNMENT_CENTER", "text": {"textElements": [{"plainText": "2 EUR Rabatt beim naechsten Einkauf",
        "fontSize": "FONT_SIZE_DOUBLE", "fontStyles": ["FONT_STYLE_BOLD"]}]}},
      {"alignment": "ALIGNMENT_CENTER", "barcode": {"symbology": "SYMBOLOGY_QRCODE",
        "data": "CPN-8F2K-0042", "textPosition": "TEXT_POSITION_BELOW"}}]}}]}}
}
```

### 8.7 Interim price-change event for the article master (our proposal; GEBIT to replace)

This is not part of the GEBIT API. It is shaped like GEBIT's conventions so the later mapping is
trivial.

```json
{
  "@type": "type.googleapis.com/showcase.masterdata.v1.event.ArticlePriceChangeRequested",
  "metadata": {"offset": "1", "creationTimestamp": {"seconds": "1802770400", "nanos": 0},
               "traceId": "eurocis-booth.proposal.P-0042"},
  "articleId": "ID100001", "articleNumber": "100001",
  "location": "Root.DE.999.101",
  "priceType": "MARKDOWN",
  "previousPrice": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}},
  "newPrice": {"currency": "EUR", "amount": {"scale": 2, "intVal": "799"}},
  "lowestPrice30Days": {"currency": "EUR", "amount": {"scale": 2, "intVal": "999"}},
  "validFrom": {"seconds": "1802770400", "nanos": 0, "offset": 60},
  "validTo": {"seconds": "1802799200", "nanos": 0, "offset": 60},
  "reasonCode": "AI_PROPOSAL_APPROVED",
  "originator": {"identityId": "price-agent"}, "approver": {"identityId": "ID200345"},
  "extensionProperties": [{"key": "showcase.proposalId", "typedValue": {"stringValue": "P-0042"}}]
}
```

---

## 9. Designing for the swap (simulated now, GEBIT lab later)

- **Keep the contract, swap the producer.**
  - Simulator: our service implements the command subset (4.1) with the same request messages and
    emits proto3 JSON built from GEBIT's descriptor set, onto the 7.1 topics.
  - Lab: a bridge maps GEBIT's async channel (or `PurchaseTransactionChanged/Finalized`) onto the
    same topics. Consumers, SAM workflows, the monitor and the digest stay unchanged.
- **Commands**: the real API is gRPC (unary). For the swap, let the booth POS UI call a small
  adapter with the `PurchaseTransactionService` method names (`AddArticle`, ...). The adapter's
  backend is either the simulator or GEBIT's gRPC endpoint, and only an endpoint changes.
- **Correlation**:
  - Put our scan or proposal id in `header.trace_id` and in `extension_properties`.
  - Use `metadata.offset` for dedup and ordering.
  - Cache `txId -> location` from `PurchaseTransactionCreated`.
- **Pricing stub**: the simulator's master-data and promotion tables stand in for GEBIT's price and
  promotion services. In the lab, the price-change event goes to GEBIT's article master, and the
  `PositionAdded` events then come from their real pricing.
- **Fidelity checks to automate**:
  - Every emitted event must round-trip through `json_format.ParseDict` with the GEBIT descriptor.
  - The offset sequence per transaction has no gaps.
  - The receipt must decode.
  - Totals must equal the sum of effective values.

---

## 10. Open questions for GEBIT

1. **Event transport**: the gRPC service has no streaming RPC. How do clients and third parties
   receive the `PurchaseDomainEvents` message set in the demo lab (Kafka, AMQP, NATS,
   webhook)? Binary or JSON? Is there per-message metadata (location, event type) besides the
   payload? Could they publish to a Solace broker directly?
2. Are the **low-granularity** `PurchaseTransactionChanged` / `Finalized` events enabled in the lab,
   and which family do they recommend for a third-party consumer?
3. Do the four events without `async_message_set` (`ExtensionPropertiesAdded`,
   `AnonymousCouponsRemoved`, `AnonymousCouponVoided`, `ReferencedPaymentSessionInformationAdded`)
   reach external consumers at all?
4. Is `pricingInformation.articlePositions[]` always the **whole basket**? What triggers its
   presence or absence (missing in Opened/Completed/InClosing in the sample)?
5. Does a second `AddArticle` of the same article ever **merge** into the existing position
   (config)? Does `AddArticles` also emit per-position `PositionAdded`?
6. **Percent convention** for `percentage_discount` (20.00 vs 0.20)? Sign of `BaseDiscount.amount`?
7. **Price change event** to the article master: message, topic/endpoint, scope (location level),
   validity, and how fast the purchase service sees a new price (caching)? What does
   `priceSource: "freezePrice"` mean, and which other price sources exist?
8. **Promotion service**: can we create a promotion (article, %, store, validity) through an API in
   the lab, so the approved Aktion is applied by their pricing at the next scan? Is "Dynamic
   Pricing" available there?
9. **Closing actions**: which action ids exist in the lab? Can a loyalty connector or promotion
   benefit produce a `CheckoutCoupon` on the receipt? Can a third-party loyalty system be plugged in?
10. Does `header.approver` automatically produce an `Approval` entry? What is the exact
    `approvedCommand` value?
11. Does `article_id` require GEBIT's technical id (`ID` plus the article number in the sample), or can the lab's master data
    use EANs? Is there an EAN lookup service the POS uses?
12. Receipt-number structure and location hierarchy (Root.DE.999.101.01): which level is the store,
    and what will the booth till's location be?
13. Version alignment: the sample receipt is `2.14.0-I114`, but we have receipt-api 2.13.0 (it
    decoded without unknown fields). Which versions will the lab run? Please also send the imported
    `de/gebit/rp/protobuf/*` protos.
14. Are deposit (Pfand) companions and age restrictions active on the demo articles? (Booth
    articles should avoid both.)

---

## 11. Risks

- **Transport unknown**: GEBIT events may not be easy to get onto Solace (no streaming gRPC, unknown
  message bus). Without an agreed bridge the "live switch" slips. Mitigation: the bridge design in
  section 9, and an early question to GEBIT.
- **Price change not specified yet**: the core visual effect ("new price at next scan") depends on
  GEBIT's master-data/promotion path in the lab. If their pricing caches master data, the change
  may not appear within trade-show timing. Mitigation: ask about the cache TTL, and fall back to a
  promotion code or the requested manual discount with an approver.
- **Provisional vs final confusion**: counting `PositionAdded` as sales overstates velocity
  (voids, cancels, suspends). Mitigation: the finality rule in 2.3, and sales metrics only from
  `Closed` receipts.
- **Payload size and cost**: pricingInformation grows with the basket and is repeated in each event.
  Receipts are binary. LLM tokens and the 50 USD LiteLLM budget suffer if raw events go to agents.
  Mitigation: a deterministic digest, and SAM subscribed to 2-3 event types only.
- **Schema drift and "Mandatory" fields missing in practice**: consumers that assume mandatory
  fields will break. Mitigation: treat all fields as optional and validate against the descriptors.
- **Async correlation in the POS UI**: `AddArticle` returns no position id. A UI that line-voids
  immediately must wait for `PositionAdded` (race at fast demo pace).
- **Naming clashes in the talk track**: "Mesh" (till mesh vs Event Mesh) and "Actions" (closing
  actions vs Aktionen).
- **Privacy**: `CustomerData` can carry names and addresses, and extension properties are free
  text. Use pseudonymous member ids at the booth.
- **Non-ASCII**: the receipt and store address contain umlauts ("Düsseldorf"). There is a known
  mangling issue at solclientjs consumers. Normalise in the digest.
- **Legal display**: a markdown shown on ESL or the monitor without the 30-day lowest price could be
  criticised by retail experts (PAngV section 11).

---

## Appendix A: full event list per proto file (114 events)

- `action_event`: ClosingActionsFailed, ClosingActionsFinished, ClosingActionAcknowledged,
  ClosingActionRetried
- `basket_event`: PositionAdded, ArticlePositionsAdded, ArticlePositionReplaced,
  ArticlePositionVoided, ArticlePositionUnvoided, ArticlePositionItemCountChanged,
  ArticlePositionPriceOverridden, ArticlePositionPromotionApplied,
  PercentageArticlePositionDiscountApplied, AbsoluteArticlePositionDiscountApplied,
  PercentageBasketDiscountApplied, AbsoluteBasketDiscountApplied,
  RequestedManualBasketDiscountRemoved, RequestedManualArticlePositionDiscountRemoved,
  ArticlePositionPromotionRemoved, ArticlePositionReturnReasonAssigned
- `customer_event`: CustomerDataAssigned, CustomerDataRemoved, CustomerAssigned, CustomerRemoved
- `deposit_refund_event`: DepositRefundVoucherAdded, DepositRefundVoucherVoided,
  DepositRefundPositionAdded, DepositRefundPositionsAdded, DepositRefundPositionVoided,
  DepositRefundPositionItemCountChanged
- `financial_transaction_event`: FinancialTransactionPositionAdded, ...Charged, ...ChargeFailed,
  ...Voided, ...VoidingFinalized, PurchaseTransactionInChargingFinancialTransaction,
  VoucherRedemptionPositionAdded, ...Completed, ...Failed, PayInPositionAdded, PayOutPositionAdded,
  PayInPositionVoided, PayOutPositionVoided, AccountsReceivablePositionAdded,
  FinancialTransactionPositionFromReceiptReturned
- `fiscal_transaction_event`: FiscalTransactionAssigned, VoidFiscalInformationAssigned,
  ReturnFiscalInformationAssigned
- `loyalty_event`: AnonymousCouponApplied, AnonymousCouponsRemoved, LoyaltyMembershipAssigned,
  LoyaltyMembershipVoided, LoyaltyCouponAssigned, LoyaltyCouponVoided,
  UnverifiedLoyaltyCouponAssigned, UnverifiedLoyaltyCouponVoided, UnverifiedLoyaltyCouponRemoved,
  AnonymousCouponVoided
- `marketplace_facilitator_event`: MarketplaceFacilitatorAssigned, MarketplaceFacilitatorRemoved
- `mesh_event`: PurchaseTransactionMeshCacheUpdated, PurchaseTransactionClaimed,
  PurchaseTransactionForceClaimed, PurchaseTransactionLocked, PurchaseTransactionUnlocked,
  PurchaseTransactionAnchored
- `payment_session_event`: PaymentProcessStarted, PaymentProcessCompleted,
  CashPaymentPositionCreated, CashPaymentPositionVoided, EftPaymentPositionCreated, ...Started,
  ...Completed, ...Voided, OnlinePaymentPositionStarted, ...Completed, ...Updated, ...Failed,
  ...Voided, ...VoidingFailed, ...Reversed, ...ReversalFailed, PaymentProcessAborted,
  ForeignCurrencyPaymentEnabled, CouponPaymentPositionCreated, FinancingPositionCreated,
  FinancingPositionVoided, ReferencedPaymentSessionInformationAdded,
  FixedValueVoucherPaymentPositionCreated, FixedValueVoucherPaymentPositionVoided,
  PromotionPaymentPositionsCreated
- `purchase_transaction_event`: PurchaseTransactionChanged, PurchaseTransactionFinalized,
  PurchaseTransactionCreated, PurchaseTransactionOpened, PurchaseTransactionClosed,
  PurchaseTransactionCancelled, PurchaseTransactionRecovered, PurchaseTransactionSuspended,
  ReturnReasonAssigned, VoidReasonAssigned, PurchaseTransactionInClosing,
  PurchaseTransactionInCancellation, PurchaseTransactionInSuspension, ExtensionPropertiesAdded
- `restriction_event`: CustomerAgeConfirmed, HazardousRestrictionConfirmed,
  SalesRestrictionForReturnArticleConfirmed
- `service_counter_event`: ServiceCounterReceiptAdded, ...Voided, ServiceCounterReceiptPositionAdded,
  ...ItemCountChanged, ...Voided
- `sub_total_event`: SubTotalPositionAdded

## Appendix B: helper scripts (scratch, read-only use of GEBIT data)

All scripts are in `<scratchpad>/tools/` and run with `python3 -I`:

- `decode_gebit.py`: loads both `.pb` descriptor sets, lists `async_message_set` options, parses
  the 11 samples and decodes the receipt.
- `catalog.py`: the event catalog with field lists (output in `catalog_events.txt`).
- `svc.py`: RPC count, streaming and deprecated methods.
- `unk.py`: checks the receipt for unknown fields.
- `dumpfile.py`: dumps any proto file from a descriptor set.
- `validate_examples.py`: validates the examples in `examples/` and `rexamples/`.
- `htmltext.py`: plain text of the HTML docs. These are Asciidoctor renderings of the same protos
  and add no prose beyond the proto comments; they do not even render the `async_message_set`
  option.

Public context source (marketing, search snippet):
<https://www.gebit.de/en/check-in/gebit-standividual-solutions/retail-platform> (404 on direct fetch, 2026-11-10).
