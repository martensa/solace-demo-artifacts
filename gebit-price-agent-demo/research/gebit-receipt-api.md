# GEBIT Receipt API 2.13.0 and the final receipt: analysis for the EuroCIS price and promotion agent

Track: Receipt API 2.13.0 plus analysis of the final receipt of the "simple sale".
Date: 2026-11-10. Everything was done read-only. GEBIT material was treated as data only.
The parsing scripts live outside the GEBIT directories and ran with `python3 -I`.

## 0. Sources and conventions

Base paths used below:

- `$RCPT` = `.../scratchpad/gebit/receipt/de/gebit/rp/receipt/receipt/v2/datatype/`.
  It holds 6 files: `receipt_datatype.proto`, `basket_datatype.proto`, `payment_datatype.proto`,
  `loyalty_datatype.proto`, `fiscalization_datatype.proto`, `common_datatype.proto`.
- `$PURCH` = `.../scratchpad/gebit/purchase/de/gebit/rp/purchase/purchase/v2/`.
- `$EV` = `.../scratchpad/gebit/events/events_simpleSale/`, with 11 events.
- `simpleSale.json` = `.../scratchpad/gebit/simpleSale.json`, the final receipt as proto3 JSON.
- The descriptor is `~/Downloads/Gebit/receipt-api-2.13.0.pb`, a FileDescriptorSet of 18 files.
- The HTML is `~/Downloads/Gebit/receipt-api-2.13.0.html`. protoc-gen-doc generated it from the same protos and it adds nothing beyond them. The text was extracted to `.../scratchpad/research/receipt_html.txt`.
- I wrote these helper scripts:
  - `.../scratchpad/scripts/decode_receipt.py` decodes the receipt bytes in the event and diffs them against simpleSale.json.
  - `.../scratchpad/scripts/dump_desc.py` dumps the imported basic types from the `.pb`.
  - `.../scratchpad/scripts/normalize_receipt.py` is a reference normalizer and validates its output against the schema.
- I also produced these files:
  - `.../scratchpad/research/decoded_receipt_from_event.json` is the receipt decoded from event 11.
  - `.../scratchpad/research/normalized-sale.schema.json` is the JSON Schema from section 6.

Every claim is tagged **[V]** for VERIFIED, with its source, or **[A]** for ASSUMPTION or inference.

Parity check [V]: all 447 fields in the `.pb` descriptor, by name and number, also appear in the extracted `.proto` sources. The sources, the descriptor and the HTML describe the same API 2.13.0. Command: an inline python3 -I check that walked the descriptor against the source text.

---

## 1. Receipt structure (exact field names)

### 1.1 Top level: `Receipt` (`$RCPT/receipt_datatype.proto:26-152`) [V]

| # | Field | Type | Notes |
|---|-------|------|-------|
| 1 | `receipt_id` | string | equals `purchase_transaction_id` (the same UUID in the sample) [V] |
| 2 | `receipt_type` | string | `"SALE"` in the sample; the API gives no list of values [V] |
| 3/4/5 | oneof `receipt_status`: `closed_receipt` / `canceled_receipt` / `suspended_receipt` | | `ClosedReceipt.taxes` = map<tax class, Tax> (`:157-162`); `CanceledReceipt{cancel_reason, cancel_reason_code, recovery_data: Any}`; `SuspendedReceipt{resume_data: Any}` |
| 6 | `receipt_number` | string | 29 digits in the sample (structure: section 7); our simulator uses `10101270216000042` |
| 7 | `location` | string | `Root.DE.999.101.01` (our booth till), the hierarchical till location |
| 8 | `store_address` | StoreAddress | `company_name, store_name, street, house_number, postal_code, city, country_name, tax_number, vat_number, extension_properties` (`:271-302`) |
| 9/10/11 | `created_at`, `opened_at`, `finalized_at` | OffsetTimestamp | `{timestamp: google.protobuf.Timestamp, offset: sint32 minutes}` (descriptor) |
| 12 | `employee` | Employee | `employee_id, employee_number, employee_session_id` (`:198-208`) |
| 13 | `cashdrawer_id` | string | a test cash-drawer name in the sample; the till id (`01`) in our simulator |
| 14 | `pricing_mode` | enum | `PRICING_MODE_GROSS` / `_NET` |
| 15 | `currency` | string | ISO 4217 |
| 16/17 | `total`, `net_total` | Decimal | gross and net receipt total |
| 18 | `basket` | Basket | see 1.2 |
| 19 | `payment_session` | PaymentSession | see 1.4 |
| 20 | `fiscal_transaction` | FiscalTransaction | see 1.6 |
| 21-24 | `return_reason(_code)`, `void_reason(_code)` | string | |
| 25 | `receipt_reference` | ReceiptReference | `referenced_receipt_id, referenced_receipt_number, receipt_reference_type (RESUME / VOID / PAYMENT_EXCHANGE), fiscal_information map` (`:213-249`) |
| 26 | `loyalty` | Loyalty | see 1.5 |
| 27 | `customer` | CustomerData | `customer_id, customer_name, customer_number, customer_type, customer_addresses[], vat_id, capturing_information` (`:307-332`) |
| 28 | `approvals` | repeated Approval | `approver_id, approved_command, approved_at` (`:254-264`): approvals are first-class in the receipt |
| 29 | `extension_properties` | repeated Property | `{key, typed_value: TypedValue}` |
| 30 | `application_mode` | string | for example MCO, SCO attendant or bakery (`:131-133`) |
| 31 | `marketplace_facilitator` | MarketplaceFacilitator | |

Basic types, dumped from the `.pb` with `dump_desc.py` [V]:

- `Decimal { string value }`, for example `{"value":"9.99"}`. It follows the google.type.Decimal grammar, per the HTML.
- `OffsetTimestamp { Timestamp timestamp; sint32 offset }`, for example `{"timestamp":"2027-02-16T13:20:01.412Z","offset":60}`. The time is in UTC and `offset` is in minutes, so 60 means CET.
- `TypedValue` is a oneof of `string_value`, `integer_value`, `bool_value`, `decimal_value`, `timestamp_value`, `offset_timestamp_value`, `date_value`, `any_value`, `list_value` and so on.
- `FormattedContent { repeated Line lines }`. Each `Line` has an `alignment` and a oneof of `text` (`TextLine{text_elements[]{plain_text, font_size, font_styles[]}}`), `image` (`{type, data, name}`) or `barcode` (`{symbology, data, text_position}`). Symbologies include `EAN8`, `EAN13`, `UPC_A`, `CODE128`, `EAN128`, `QRCODE`, `DATAMATRIX`, `PDF417` and `GS1_DATABAR*`.

### 1.2 Basket and lines (`$RCPT/basket_datatype.proto`) [V]

`Basket` (`:23-46`) has these fields:

- `receipt_positions[]`
- `deposit_refund_vouchers[]`
- `service_counter_receipts[]`
- `set_discounts[]`, the basket-level discounts
- `basket_rounding`, of type `BasketRoundingDiscount{rounding_amount}`

`ReceiptPosition` (`:53-84`) has these fields:

- `position_id`
- `created_at`, which is the scan time. It equals `PositionAdded.createdAt` exactly, to the nanosecond [V].
- `description` (`"GEBIT Ente (Quietscheente gelb)"` for article `100001` in our seed)
- `printout_description`
- `extension_properties[]`
- oneof `receipt_position_details`. It holds either `revenue_position` or `subtotal_position`. A subtotal is informative only, `{subtotal_amount}`.

`RevenuePosition` (`:90-153`) has these fields:

- oneof `position_type`. It is either `sale_position` (empty) or `return_position{receipt_reference: SaleReceiptReference, return_reason_code}`.
- `effectual`. This must be true for the line to count.
- `manually_voided`. A line void sets `effectual=false`.
- `effective_position_value`. This is the final gross value after all item discounts, and it is negative for reductions.
- `taxes`, a map<tax class, Tax>.
- oneof `position_details`. The options are `article_position`, `deposit_refund_position`, `financial_transaction_position`, `voucher_redemption_position`, `pay_in_position`, `pay_out_position`, `accounts_receivable_position` and `service_position`.

`ArticlePosition` (`:215-310`) holds the line for an article:

| Field | Meaning |
|-------|---------|
| oneof `article_type` | `regular_article` / `deposit_article{referenced_position_id}` (Pfand) / `service_counter_article{service_counter_receipt_id}` / `other_article{article_type}` |
| `article_id`, `article_number` | `ID100001` / `100001` in our seed (GEBIT's sample uses the same `ID` + article number pattern) |
| `item_count` (sint32) | the number of countable items, negative for returns |
| `unit` (enum Unit) | `UNIT_PIECE`, `UNIT_KILOGRAM`, ... (`common_datatype.proto:18-76`) |
| `quantity` (Decimal) | the dimension (weight and similar). It is 1 for pieces and always positive |
| `tare` | optional |
| `price_per_unit` | always positive. In gross mode it includes VAT (the sample shows 8.67) |
| `price_source` | `"freezePrice"` in the sample. It records where the price came from, for example a supplied price that overrules master data |
| `dimension_source` | |
| `base_position_value` | the value before discounts, including tax |
| `position_discounts[]` | `PositionDiscount{base_discount, set_discount_id, item_count}` |
| `capturing_information` | `{input_method (scan/manual/...), input_type (EAN/PLU/article no.), input_value}` (`common_datatype.proto:170-183`) |
| `scale_print_lines[]`, `scale_weighing_id` | for certified scales |
| `agency_id` | concessionaire |
| `article_return_position_properties{original_price_per_unit}` | for returns |
| `basket_rounding_fraction_discount` | |

Prices and discounts (`:710-780`) [V]:

- `BaseDiscount` has `discount_id`, `discount_type` (`DISCOUNT_TYPE_ABSOLUTE` / `_RELATIVE` / `_NEW_PRICE`), `description`, `amount`, `percentage`, `extension_properties`, `promotion_id` (set to the promotion's id when a promotion triggered the discount) and `reason_code`.
- `SetDiscount{base_discount, position_discounts[] (ids)}` is the basket-level discount, distributed to positions.
- A live single-article promotion appears in the receipt in three places:
  - `ArticlePosition.position_discounts[].base_discount{promotion_id, amount, discount_type}`
  - `base_position_value` greater than `effective_position_value`
  - a markdown in article master data, if used, shows up as a lower `price_per_unit` (and probably a different `price_source`) [A]

Other position types are relevant for filtering:

- `ServicePosition`: `article_id`, `item_count`, `price_per_item`, `position_discounts`, `referenced_position_id`
- `DepositRefundPosition`
- `FinancialTransactionPosition`: type `VOUCHER` (multi-purpose voucher), `CASH_INFLOW` or `SINGLE_PURPOSE_VOUCHER`. It also carries `formatted_receipt_block`.
- `VoucherRedemptionPosition`: redemption at a payment provider, with `formatted_receipt_block`.
- `PayIn`, `PayOut` and `AccountsReceivable` positions.

### 1.3 Taxes (`$RCPT/common_datatype.proto:112-152`) [V]

`Tax { tax_amount; extension_properties; oneof tax_details { PercentageTax percentage_tax | FlatTax flat_tax } }`
and `PercentageTax { tax_rate (percent, e.g. "19.00"), net_amount, gross_amount = net_amount + tax_amount }`.

- Receipt level: `closed_receipt.taxes["C"] = {taxAmount 1.38, percentageTax{taxRate 19.00, netAmount 7.29, grossAmount 8.67}}`.
- Line level: `revenue_position.taxes["C"]` holds the same values.
- The tax class is the map key. In this sample `"C"` is 19% [V]. Whether the class letters are configuration dependent is not confirmed [A]. The proto comment for `PaymentSurcharge.taxes` shows `"A", "B"` as examples (`payment_datatype.proto:359`).

### 1.4 Payments (`$RCPT/payment_datatype.proto`) [V]

`PaymentSession{payments[], extension_properties}`. `PaymentPosition` (`:34-124`) has these fields:

- `payment_position_id`
- `payment_transaction_type`, one of `PAYMENT`, `CHANGE`, `ROUNDING` or `CASHBACK`
- `means_of_payment_variant`
- `location`, the location of the client (MCO/MMCO/MSCO). It holds a client id placeholder in the sample, so it cannot be used as the store id.
- `checkout_client_transaction_id`
- `amount`
- `effectual`
- `foreign_currency_information`
- `payment_position_reference`
- oneof `detailed_payment`: `cash_payment_position{manually_voided}`, `eft_payment_position` (card data such as `payment_descriptor.card{card_type, payment_scheme, card_number, ...}` and `payment_receipts[]{payment_receipt_type CUSTOMER/RETAILER, formatted_receipt, print_suggestion}`), `online_payment_position`, `coupon_payment_position{coupon_position_id}`, `promotion_payment_position{description, trigger: PromotionActionTrigger}`, `financing_position` or `fixed_value_voucher_position{voucher_number}`
- `capturing_information`
- `associated_receipt_positions[]`
- `created_at`

In the sample, cash `PAYMENT 10` and `CHANGE -1.33` net to 8.67, which equals `total`.

### 1.5 Loyalty section (`$RCPT/loyalty_datatype.proto`) [V]

`Loyalty { anonymous_coupons[], loyalty_memberships[], loyalty_purchase_result }` (`:21-31`):

- `AnonymousCoupon` (`:39-68`): `prefix`, `promotion_code`, `value` (for industrial coupons, "Preisnachlassgutschein"), `description`, `coupon_position_id`, `voided`, `capturing_information`, `applied`.
- `LoyaltyMembership` (`:73-123`): `membership_position_id`, `membership_identification_value` (the scanned card value), `membership_id`, `program_id`, `program_name`, `customer_id`, `anonymous`, `voided`, `verified`, `coupons[]` (LoyaltyCoupon), `accounts` (map<account type, LoyaltyAccount{account_id, account_type, account_description, account_currency, account_balance_before_purchase}>), `receipt_content` (FormattedContent, the text to print on the receipt), `membership_preferences[]` (for example a digital receipt preferred), `capturing_information`.
- `LoyaltyCoupon` (`:128-158`): `coupon_position_id`, `coupon_identification_value`, `coupon_id`, `coupon_description`, `from_membership`, `applied`, `voided`.
- `LoyaltyPurchaseResult` (`:188-202`):
  - `checkout_coupons[]`
  - `earned_amounts[]` (EarnCurrency)
  - `burned_amounts[]` (BurnCurrency)
  - `deferred_purchase_report_request` (an Any to send to the loyalty system after closing)
  - EarnCurrency and BurnCurrency both have the form `{application: BenefitApplicationAttributes{program{id,name}, membership_id, benefit_id, promotion_id, reported}, account{id,name}, currency{id,name}, earned_amount|burned_amount, position_fractions[]{position_id, item_count, fraction_amount}}`.
- `CheckoutCoupon` (`:245-255`): `application`, `coupon_id`, `print_content: FormattedContent`. Per the proto comment it is a coupon that gets printed once the checkout finishes.

The sample has no membership but earns points [V]. It contains `earnedAmounts[0] = {program POINTS-ID/"POINTS", promotionId "promotion-base-points", reported true, account POINTS-ACCOUNT-ID, currency "Points", earnedAmount 4.00, positionFractions[{positionId <id of the line>, itemCount 1, fractionAmount 4.00}]}`. Per `:257-258` this is what a customer earned, or would earn as a member. The earn rule behind 4 points for 8.67 EUR is unknown [A]; one candidate is 1 point per started 2 EUR, rounded down.

### 1.6 Fiscalization and TSE (`$RCPT/fiscalization_datatype.proto`) [V]

`FiscalTransaction` (`:21-115`) has these fields:

- `fiscal_transaction_id`. It matches `FiscalTransactionAssigned.fiscalTransactionId` (the same UUID in the sample) [V].
- `attributes`, a map<id, FiscalAttribute>
- `fiscal_transaction_status`, either `STARTED` or `FINISHED`
- `started_timestamp`, `finished_timestamp`. These are internal times only. The legally relevant TSE times are in the attributes (`:34-44`).
- `started_result_code`, `finished_result_code`. Values: `NOT_APPLICABLE`, `SUCCESS`, `SUCCESS_WITH_WARNING`, `ERROR`, `DUPLICATE`.
- `fiscal_receipt_or_report_type`
- `external_errors[]`
- `extension_properties`
- `service_failure`

`FiscalAttribute` (`:122-162`) has `fiscal_attribute_id` (country-prefixed), `label`, `value` (always a string), `value_type` (`STRING` / `INT64` / `ISO_OFFSET_DATE_TIME` / `JSON`), `required_on_receipt`, `required_in_transaction_data`, `is_barcode` and `barcode_types[]` (`QR_CODE`, `CODE128`, ...).

GEBIT's sample receipt carries these 13 DE attributes [V]. The ids, labels and flags below come from the sample. The values are illustrative and do not reproduce GEBIT's sample values: they show what our simulator would write for the 7.99 EUR booth sale of `gebit-purchase-api.md` section 8.5 (receipt sequence 42, signatures marked as in section 5).

| id | label | value (illustrative) | on receipt | in txn data |
|----|-------|----------------------|-----------|-------------|
| `DE_TransactionNo` | Transaktionsnummer | 42 (INT64) | yes | yes |
| `DE_TimestampStart` | Start | 2027-02-16T13:20:01.530Z | yes | yes |
| `DE_TimestampFinish` | Ende | 2027-02-16T13:20:07.402Z | yes | yes |
| `DE_SignatureCounterStart` | Signaturzaehler | 83 | no | no |
| `DE_SignatureCounterFinish` | Signaturzaehler | 84 | yes | yes |
| `DE_SignatureStart` | Signaturwert | `++DEMO+SIMULATOR++` plus non-verifiable text | no | no |
| `DE_SignatureFinish` | Signaturwert | `++DEMO+SIMULATOR++` plus non-verifiable text | yes | yes |
| `DE_SerialNoTill` | Seriennummer Kasse | `Root.DE.999.101.01` (= location of our booth till) | yes | yes |
| `DE_SerialNoTSS` | Seriennummer TSE | `SIMULATED-` plus 64 hex chars | no | no |
| `DE_ProcessType` | TSE_TA_VORGANGSART | `Kassenbeleg-V1` (DSFinV-K constant) | no | yes |
| `DE_ProcessData` | TSE_VORGANGSDATEN | `Beleg^7.99_0.00_0.00_0.00_0.00^7.99:Bar` | no | yes |
| `DE_ReceiptType` | BON_TYP | `Beleg` (DSFinV-K constant) | no | yes |
| `DE_QRCode` | (none) | `V0;...` (12 fields, see below) | no, but `is_barcode=true`, `QR_CODE` | no |

Observations on GEBIT's sample [V], with the decoding done by inline python:

- `DE_QRCode` has 12 fields separated by `;`:
  - 0: `V0`
  - 1: the till serial (= DE_SerialNoTill)
  - 2: `Kassenbeleg-V1` (= ProcessType)
  - 3: ProcessData
  - 4: TransactionNo
  - 5: SignatureCounterFinish
  - 6: TimestampStart
  - 7: TimestampFinish
  - 8: `ecdsa-plain-SHA384`
  - 9: `unixTime`
  - 10: the signature (= DE_SignatureFinish)
  - 11: a base64 SPKI public key (120 bytes, EC P-384)

  This matches the DSFinV-K QR layout, which I know from domain knowledge [A]. The mapping to the attributes is [V].
- `DE_SerialNoTSS` equals SHA-256 of the uncompressed EC public key point (`0x04||X||Y`, 97 bytes) taken from the QR code. The computed hash matches the attribute exactly [V]. This is the BSI serial-number convention [A].
- GEBIT's own test fiscalization is a simulator. Both signatures start with `++FCC+SIMULATOR++`, and the result is not valid base64 [V], so it cannot be verified. That is deliberate marking [A]. FCC is probably the "Fiskal Cloud Connector" of a cloud TSE vendor [A].
- In ProcessData, `Beleg^<gross amounts per VAT slot>^<payments amount:type>` holds the gross total in the 19% slot, 0.00 in the other slots and the cash amount (`Bar`) as payment. That the slot order is 19 / 7 / 10.7 / 5.5 / 0 % is [A], from DSFinV-K domain knowledge.
- Per the proto comment, when a value may appear either as text or as a barcode, both attributes carry `required_on_receipt=false` and the till itself must know that it has to print one of them (`:142-148`) [V].

### 1.7 Footer and additional texts [V]

The Receipt API has no dedicated header, footer or free-text fields. Printable content exists only in these places:

- `ReceiptPosition.printout_description`
- `ScalePrintLine.text`
- `FinancialTransactionPosition.formatted_receipt_block`, which holds things like prepaid PINs
- `VoucherRedemptionPosition.formatted_receipt_block`
- `OnlinePaymentPosition.receipt_position_text`, `formatted_receipt_block`
- `EftPaymentPosition.payment_receipts[].formatted_receipt`, the card slips
- `LoyaltyMembership.receipt_content`
- `CheckoutCoupon.print_content`
- `FiscalAttribute` (`label` + `value`, with `required_on_receipt` / `is_barcode`)
- `extension_properties`, as untyped key/value data. Nothing in the API says they are printed.

Static texts such as "Vielen Dank fuer Ihren Einkauf" presumably come from the receipt print layout or configuration (COMPAS is mentioned for `application_mode`) [A].

---

## 2. How the receipt in PurchaseTransactionClosed relates to the Receipt API model

The verification ran `python3 -I .../scripts/decode_receipt.py receipt-api-2.13.0.pb 11_PurchaseTransactionClosed.json simpleSale.json ...`, with this output:

```text
raw bytes: 3040
Any.type_url: type.googleapis.com/de.gebit.rp.receipt.receipt.v2.datatype.Receipt inner bytes: 2968
unknown fields: []
diffs decoded vs simpleSale.json (after dropping defaults): 0
```

Findings [V]:

1. **The receipt is embedded as serialized bytes, not as a nested message.** `PurchaseTransactionClosed` (`$PURCH/event/purchase_transaction_event.proto:200-232`) has these fields:
   - `header`
   - `metadata{offset, creation_timestamp, trace_id}`
   - `purchase_transaction_id`
   - `closed_at`
   - `purchase_transaction_status`
   - `serialized_receipt_format` (string; `"PROTOBUF"`)
   - `serialized_receipt_content` (bytes)
   - `pricing_information`
   - `extension_properties`
   - `serialized_receipt_version` (`"2.14.0-I114"`)

   The bytes are a `google.protobuf.Any` whose `type_url` names `de.gebit.rp.receipt.receipt.v2.datatype.Receipt` and whose `value` is the Receipt. In proto3 JSON the bytes appear as base64 (about 4 KB).
2. **It is the same model.** The decoded Receipt is identical to `simpleSale.json` once proto3 default values are dropped. simpleSale.json was printed with defaults included (`"printoutDescription": ""`, `"manuallyVoided": false`, empty lists), so a JSON consumer must treat a missing field as its default.
3. **There is a version skew.** The event says the receipt content version is `2.14.0-I114`, while our docs and protos are 2.13.0. Decoding with the 2.13.0 descriptor left 0 unknown fields for this sample, but a richer 2.14 receipt may add fields. Decoders must keep unknown fields (protobuf does by default) and log `serialized_receipt_version`.
4. **Other events carry the same receipt bytes:**
   - `PurchaseTransactionFinalized`, a low-granularity event for any final status (CLOSED, CANCELLED, ...). It arrives before the matching `PurchaseTransactionChanged` (`:65-105`).
   - `PurchaseTransactionCancelled` (`:237-269`)
   - `PurchaseTransactionSuspended` (`:323-354`)

   GEBIT itself recommends the low-granularity events for many use cases (`:196-198`).
5. **The Purchase API and the Receipt API use different basic types.** This matters for the simulator and the normalizer:

   | Concept | Purchase API events | Receipt API |
   |---------|--------------------|-------------|
   | Decimal | `BDecimal{scale:int32, int_val:int64}`, e.g. `{"scale":2,"intVal":"867"}`; a zero is `{"scale":2}` because intVal is omitted (`$PURCH/datatype/common_datatype.proto:37-45`) | `Decimal{value:"8.67"}` |
   | Timestamp | `OffsetTimestamp{seconds, nanos, offset}` (flat, `:183+`) | `OffsetTimestamp{timestamp: Timestamp, offset}` |
   | Taxes | `repeated Tax{tax_class, tax_rate, tax_amount, net_amount, gross_amount}` | `map<tax_class, Tax{tax_amount, percentage_tax{tax_rate, net_amount, gross_amount}}>` |
   | Line type | `ArticlePositionType` enum (`SALE`, `RETURN`, `DEPOSIT_SALE`, `SERVICE_SALE`, ...) | oneofs `sale_position`/`return_position` + `article_type` |

6. **Content of the receipt bytes.** The receipt contains the store address, the TSE data, the loyalty results (points, checkout coupons) and the payment details. None of these appear in the fine-grained events, so **PurchaseTransactionClosed (or Finalized) is the only complete source for sales history** [V, by comparing event 11 with events 01-10].
7. **Practical parsing notes:**
   - Receipt timestamps have nanosecond precision (nine fractional digits in the sample). Python's `datetime.fromisoformat` rejects 9 fractional digits, so they must be truncated to microseconds.
   - The compact JSON receipt is 8755 bytes for a single line.

---

## 3. Fields that feed sales-velocity analytics (what the sales-history store persists)

Rule [V, from the developer note plus the proto semantics]: only data from a closed receipt is final. Positions from `PositionAdded` are provisional until `PurchaseTransactionClosed`. A `PurchaseTransactionCancelled` means nothing was sold.

**Per receipt (header):**

| Analytics need | Receipt field (proto3 JSON path) |
|----------------|----------------------------------|
| idempotency key | `receiptId` (= purchaseTransactionId), plus `metadata.offset` from the event |
| human reference | `receiptNumber` |
| final status | oneof `closedReceipt` / `canceledReceipt` / `suspendedReceipt`, plus `receiptType` |
| store / POS | `location`. `Root.DE.999.101.01` probably means Root > country DE > company 999 > store 101 > till 01 [A]; split on the last dot for `pos_id` |
| store label | `storeAddress.companyName/storeName/city` |
| sale timestamp | `finalizedAt` (UTC + `offset` minutes), plus `openedAt` for basket duration |
| channel / lane | `applicationMode` (mco / sco / ...), `cashdrawerId` |
| amounts | `total` (gross), `netTotal`, `closedReceipt.taxes{class: taxAmount, taxRate, netAmount, grossAmount}`, `currency`, `pricingMode` |
| basket discounts | `basket.setDiscounts[].baseDiscount{amount, promotionId}` |
| tender mix | `paymentSession.payments[]{paymentTransactionType, <oneof>, amount, effectual}` |
| customer / loyalty | `customer.customerId/customerType`; `loyalty.loyaltyMemberships[]{membershipId, programId, anonymous, verified, customerId}` |
| points / coupons | `loyalty.loyaltyPurchaseResult.earnedAmounts[].earnedAmount`, `burnedAmounts[]`, `checkoutCoupons[].couponId`; `loyalty.anonymousCoupons[]{promotionCode, applied, voided}` |
| voids | `receiptReference{referencedReceiptId, receiptReferenceType=VOID}`. A void receipt must reverse the original's units |
| demo correlation | `extensionProperties[]`, receipt level and position level |

**Per line** (only `revenuePosition.articlePosition`; skip `subtotalPosition`, financial transactions, voucher redemption, pay-in/out):

| Analytics need | Field |
|----------------|-------|
| line id | `positionId` |
| scan time | `createdAt` (= the PositionAdded time) |
| article | `articlePosition.articleId`, `articleNumber`, `description` |
| GTIN (for ESL mapping) | `articlePosition.capturingInformation.inputValue` when `inputType` is EAN. It is absent in the sample, and the input_type values are unknown [A] |
| counts | `effectual` and `!manuallyVoided`; `itemCount` (signed); `unit`; `quantity` |
| sold units | `itemCount` when `UNIT_PIECE`, otherwise `itemCount * quantity` [A, derived from the comments at `:248-262`] |
| sale vs return | `salePosition` / `returnPosition` |
| article kind | `regularArticle` / `depositArticle` (exclude Pfand from velocity) / `serviceCounterArticle` / `otherArticle` |
| price paid | `pricePerUnit`, `priceSource` |
| gross before / after discount | `basePositionValue` / `effectivePositionValue` |
| net / tax | `taxes{class}.percentageTax.netAmount`, `taxAmount`, `taxRate` |
| promotion attribution | `positionDiscounts[].baseDiscount{discountId, discountType, amount, percentage, promotionId, reasonCode}` |
| points per line | `loyaltyPurchaseResult.earnedAmounts[].positionFractions[]{positionId, fractionAmount}` |

Velocity derivation [A, a design proposal]:

- velocity(article, store, bucket) = sum(`sold_units`) over effectual sale lines minus returns, bucketed by `finalized_at`. In Postgres 18, `date_bin('15 minutes', finalized_at, '2026-01-01')` does the bucketing.
- Persist `unit_price`, `price_source` and an `agent_proposal_id` hook. With those, the demo can prove "before the markdown: X units/h at 8.67; after approval: Y units/h at 6.99".
- Keep voided lines with `effectual=false`. They are not counted, but a scan followed by a void is a nice "price-shock" signal.

---

## 4. Loyalty data and a voucher for the next visit

What the receipt carries [V, section 1.5]:

- Points earned: `earned_amounts[].earned_amount`, per program, account and currency, with per-position fractions.
- Points redeemed: `burned_amounts[]`.
- Account balance before the purchase: `accounts[type].account_balance_before_purchase`.
- Coupons the customer used: `anonymous_coupons[]{prefix, promotion_code, value, applied}` and `loyalty_memberships[].coupons[]{coupon_id, applied}`.
- A coupon used as a means of payment: `PromotionPaymentPosition{trigger: PromotionActionTrigger{promotion_id, oneof anonymous_coupon{coupon_position_id} | loyalty_membership{loyalty_membership_position_id, loyalty_coupon_position_id} | unqualified}}` (`common_datatype.proto:189-232`).
- **Coupons issued for the next visit:** `loyalty_purchase_result.checkout_coupons[]`. Each is a `CheckoutCoupon{application{program, membership_id, benefit_id, promotion_id, reported}, coupon_id, print_content}`. `print_content` is a `FormattedContent` and can carry text lines plus a barcode line (`SYMBOLOGY_QRCODE`, `EAN13`, `CODE128`, ...). **This is the native slot for a "voucher for the next visit"** [V].

Can the agent put a voucher on the receipt?

- The Purchase API has no command that injects a checkout coupon, or earned or burned amounts [V]. `grep -i "checkout|earn|burn|PurchaseResult"` over `$PURCH` finds nothing relevant, and "CheckoutCoupon" appears 0 times in purchase-api-2.50.0.html. Checkout coupons are therefore produced inside GEBIT, probably by the promotion engine or loyalty system at closing [A].
- Generic hook: `AddExtensionProperties{purchase_transaction_id, extension_property_bearer_type (PURCHASE_TRANSACTION / ARTICLE_POSITION / PAYMENT_SESSION / PAYMENT_POSITION), extension_property_bearer_id, extension_properties[]}` (`$PURCH/command/purchase_transaction_command.proto:473-490`; enum in `purchase_transaction_enum.proto:167-183`). The sample proves that transaction-level and position-level extension properties flow into `Receipt.extension_properties` and `ReceiptPosition.extension_properties` (`foo/bar`, `baz/42`, `john/doe`) [V]. Whether the receipt print layout renders them is unknown, as is whether the command is accepted in `IN_PAYMENT` [A, ask GEBIT].
- **Timing makes the paper receipt unsuitable** [A, from lab numbers]. `PurchaseTransactionClosed` arrives after the receipt is final; in the sample, finalized_at is 16:25:29.18 and closed at 16:25:29.18. The measured SAM agent nodes take 5-11 s and a 4-node workflow takes 14-20 s, so a voucher computed after Closed cannot appear on the same paper receipt. Recommended options:
  1. Show the voucher on the booth monitor and the visitor's phone, with a QR code to a landing page, about 15 s after payment. In simulation, also fill `checkout_coupons[]` in the simulated receipt so the data path is identical.
  2. Pre-compute it at `PaymentProcessStarted` and attach it through `AddExtensionProperties` before closing. This needs GEBIT confirmation and is a risky trade-show path.
  3. Ask GEBIT to configure a real promotion in their promotion engine whose checkout coupon the agent can switch on.
- Redemption on the next visit fits existing commands [V]:
  - `ApplyAnonymousCoupon{prefix, promotion_code, capturing_information}` (`$PURCH/command/loyalty_command.proto:25-44`) leads to `Loyalty.anonymous_coupons[]` with `applied=true`, and the discount shows up as `PositionDiscount.base_discount.promotion_id`.
  - Alternatively, `AssignLoyaltyCoupon{coupon_identification_value}` (`:115-134`) for member coupons.
- Use a promotional coupon (Rabattcoupon, e.g. "-20% on the duck next visit"), **not** a monetary "Gutschein". In GEBIT, a monetary voucher is a financial transaction (`FINANCIAL_TRANSACTION_TYPE_VOUCHER` / `SINGLE_PURPOSE_VOUCHER`, `basket_datatype.proto:492-505`) [V]. Under German VAT law, single-purpose and multi-purpose vouchers have their own rules [A, general knowledge].
- Loyalty ids: visitors are real people. Use pre-printed demo loyalty cards with fictional personas (`AssignLoyaltyMembership{membership_identification_value}`, `loyalty_command.proto:76-92`), and store only a pseudonymised `member_ref` [A, recommendation].

---

## 5. Fiscalization: what a simulator must fill and what to avoid

Legal frame:

- **[V]** § 6 KassenSichV requires these receipt elements (fetched from `https://www.gesetze-im-internet.de/kassensichv/__6.html`):
  1. full name and address of the business
  2. the issue date, plus the start and end times of the transaction
  3. the quantity and type of goods
  4. the transaction number
  5. the amount, the tax amount and the tax rate
  6. the serial numbers of the recording system and of the security module
  7. the check value (Pruefwert) and the signature counter

  They can be shown as plain text or as a QR code following DSFinV-K.
- Mapping to the receipt [V, field semantics]:
  1. `store_address`
  2. `DE_TimestampStart` / `DE_TimestampFinish`; per `:34-44` these are the legal times, not `started_timestamp`
  3. basket lines
  4. `DE_TransactionNo`
  5. `total` and `closed_receipt.taxes`
  6. `DE_SerialNoTill` and `DE_SerialNoTSS`
  7. `DE_SignatureFinish` and `DE_SignatureCounterFinish`

  Alternatively, `DE_QRCode` covers them.
- **[V]** § 379 Abs. 1 AO (fetched from `https://www.gesetze-im-internet.de/ao_1977/__379.html`) makes it an administrative offence, among other acts, to issue factually incorrect Belege (Nr. 1) or to misuse or not protect a required recording system (Nr. 4-5). It applies when the act makes tax evasion possible.
- **[V]** DSFinV-K knows a training receipt type `AVTraining` alongside `Beleg`, `AVBelegstorno`, `AVBelegabbruch` and others (fiskaly mapping, `https://developer.fiskaly.com/dsfinvk/process_types_business_transaction_types`).
- **[A]** At the booth no real money changes hands, so there is no business transaction and the obligations of § 146a AO / KassenSichV do not apply to the demo itself. The risk is reputational and comes from look-alike documents: tax-compliance vendors exhibit at EuroCIS, and their QR-check apps validate DSFinV-K codes. This is not legal advice; GEBIT, as a POS vendor, should confirm it.

What the simulator should fill, so that structure and code paths match the live system:

- `fiscal_transaction.fiscal_transaction_id`: a UUID, also emitted in a simulated `FiscalTransactionAssigned`.
- Status and result codes: `fiscal_transaction_status=FISCAL_TRANSACTION_STATUS_FINISHED`, `started_result_code`/`finished_result_code=RESULT_CODE_SUCCESS`.
- `started_timestamp` / `finished_timestamp`.
- The same 13 `DE_*` attribute ids, labels, `value_type`, `required_on_receipt`, `required_in_transaction_data`, `is_barcode` and `barcode_types` as in the sample, so the normalizer and UI parse identical shapes.
- Values that are obviously simulated:
  - `DE_TransactionNo`: a monotonic demo counter.
  - `DE_SignatureCounterStart/Finish`: monotonic, +2 per transaction, because start and finish are consecutive within one transaction in the sample [A].
  - `DE_SerialNoTill` = `location`.
  - `DE_ProcessType` = `Kassenbeleg-V1`.
  - `DE_ProcessData` computed from the basket (gross per VAT slot, payments).
  - Signatures: mirror GEBIT's own convention and prefix them with a marker such as `++DEMO+SIMULATOR++`, followed by deliberately non-verifiable content. Do not use a real ECDSA signature.
  - `DE_SerialNoTSS`: `SIMULATED-` plus a hash, or GEBIT's own simulator style. Never a certified TSE serial.
- Detection rule in the normalizer: `simulated = any(attribute value contains "SIMULATOR")`. It flags both our simulator and GEBIT's FCC simulator [V for GEBIT's sample].
- A minimal alternative is an empty `FiscalTransaction` with `started_result_code=RESULT_CODE_NOT_APPLICABLE` (meaning no fiscal step was taken, `:95-96`). It is honest but less faithful.

What to avoid [A, recommendations]:

- **Do not** produce cryptographically valid signatures with a self-made key, or a real public key in the QR code. A check app would report "valid signature from an uncertified key", which is worse than an obviously fake one.
- **Do not** print or render the DSFinV-K QR code at the booth. If a code is shown at all, it should link to a page that explains the demo.
- **Do not** use a real retailer's name, address, Steuernummer or USt-IdNr. The sample's VAT number is an obvious placeholder; keep a fictional "EuroCIS Demo Markt".
- **Do not** call the printout a "Kassenbeleg". Header it "DEMO - kein Kassenbeleg / Trainingsbeleg" and replace the TSE block with "TSE: Simulation". If GEBIT's lab POS has a training mode (BON_TYP `AVTraining`), use it for the live switch.
- **Do not** persist TSE signatures in the analytics DB. Only `fiscal_transaction_id`, `transaction_no` and `simulated` are needed.

---

## 6. Normalized sale record (JSON Schema) and DB sketch

The full schema is at `.../scratchpad/research/normalized-sale.schema.json` (draft 2020-12). The reference normalizer `.../scratchpad/scripts/normalize_receipt.py` produced a record from the decoded sample receipt that **validates against the schema**. It is 1798 bytes as compact JSON for a single-line receipt [V, run output].

Compact view of the schema (types abbreviated; the example values follow our simulator seed, a regular 9.99 EUR sale of article `100001`):

```json
{
  "schema_version": "1", "source": "simulator|gebit-lab",
  "receipt_api_version": "2.13.0", "event_offset": 11,
  "receipt_id": "uuid (= purchaseTransactionId)", "receipt_number": "str", "receipt_type": "SALE",
  "status": "CLOSED|CANCELED|SUSPENDED", "voided_receipt_id": "uuid|null",
  "location": "Root.DE.999.101.01", "store_id": "Root.DE.999.101", "pos_id": "01",
  "application_mode": "str|null",
  "opened_at": "date-time", "finalized_at": "date-time", "utc_offset_min": 60,
  "local_date": "date", "local_hour": 17, "basket_seconds": 18.4,
  "currency": "EUR", "total_gross": 9.99, "total_net": 8.39, "total_tax": 1.60,
  "total_discount": 0.0, "units_total": 1,
  "taxes":   [{"tax_class": "C", "rate": 19.0, "net": 8.39, "tax_amount": 1.60, "gross": 9.99}],
  "tenders": [{"kind": "cash|eft|online|coupon|promotion|financing|fixed_value_voucher|other",
               "txn_type": "PAYMENT|CHANGE|ROUNDING|CASHBACK", "amount": 10.0, "scheme": null}],
  "loyalty": {"member_ref": "h:<sha256-16>|null", "program_id": "POINTS-ID", "anonymous": true,
              "points_earned": 4.0, "points_burned": 0, "coupons_applied": [], "checkout_coupons": []},
  "customer_ref": "h:...|null",
  "fiscal": {"fiscal_transaction_id": "uuid", "transaction_no": 41, "simulated": true},
  "extensions": {"<key>": "scalar"},
  "lines": [{
    "position_id": "uuid", "line_no": 1, "scanned_at": "date-time",
    "article_id": "ID100001", "article_number": "100001", "gtin": "str|null",
    "description": "GEBIT Ente (Quietscheente gelb)", "article_kind": "regular|deposit|service_counter|other",
    "movement": "sale|return", "effectual": true,
    "item_count": 1, "unit": "PIECE", "quantity": 1.0, "sold_units": 1,
    "unit_price": 9.99, "price_source": "REGULAR",
    "base_value": 9.99, "discount_total": 0.0, "effective_value": 9.99,
    "net_value": 8.39, "tax_value": 1.60, "tax_class": "C", "tax_rate": 19.0,
    "promotion_ids": [], "discounts": [{"discount_id": "", "type": "", "amount": 0,
      "percentage": null, "promotion_id": null, "reason_code": null, "description": ""}],
    "points_earned": 4.0, "input_method": "str|null", "agent_proposal_id": "str|null"
  }]
}
```

Design choices [A]:

- Amounts are JSON numbers in major currency units, to keep them friendly for LLM and tool use. Store them in the DB as `numeric(12,2)` and quantities as `numeric(12,3)`.
- Keep the raw decoded receipt (about 9 KB) in `jsonb` for replay and forensics.
- Pseudonymise customer and member ids.

A Postgres 18 sketch follows (no pgvector needed). It is not applied anywhere.

```sql
create table sales_receipt (
  receipt_id uuid primary key, receipt_number text, status text, source text,
  receipt_api_version text, event_offset bigint,
  location text, store_id text, pos_id text, application_mode text,
  opened_at timestamptz, finalized_at timestamptz not null, utc_offset_min smallint,
  local_date date, local_hour smallint, currency char(3),
  total_gross numeric(12,2), total_net numeric(12,2), total_tax numeric(12,2),
  total_discount numeric(12,2), units_total numeric(12,3),
  member_ref text, points_earned numeric(12,2), tenders jsonb, taxes jsonb,
  fiscal_simulated boolean, voided_receipt_id uuid, extensions jsonb,
  raw_receipt jsonb, ingested_at timestamptz default now());
create table sales_line (
  receipt_id uuid references sales_receipt on delete cascade, position_id uuid,
  line_no int, scanned_at timestamptz, article_id text not null, article_number text,
  gtin text, description text, article_kind text, movement text, effectual boolean,
  item_count int, unit text, quantity numeric(12,3), sold_units numeric(12,3),
  unit_price numeric(12,2), price_source text, base_value numeric(12,2),
  discount_total numeric(12,2), effective_value numeric(12,2), net_value numeric(12,2),
  tax_value numeric(12,2), tax_class text, tax_rate numeric(5,2), promotion_ids text[],
  points_earned numeric(12,2), agent_proposal_id text,
  primary key (receipt_id, position_id));
create index on sales_line (article_id, scanned_at);
-- velocity, 15-minute buckets (sold minus returned, effectual only, no Pfand):
-- select l.article_id, r.store_id, date_bin('15 minutes', r.finalized_at, timestamptz '2026-01-01') b,
--        sum(l.sold_units) units, sum(l.effective_value) gross, sum(l.net_value) net
-- from sales_line l join sales_receipt r using (receipt_id)
-- where r.status='CLOSED' and l.effectual and l.article_kind <> 'deposit'
-- group by 1,2,3;
```

Upsert rule: `insert ... on conflict (receipt_id) do nothing`. Events can be replayed, and `metadata.offset` is monotonic per transaction [V, offsets 1..11 in the sample]. A void receipt (`receipt_reference_type=VOID`) carries negative values [V, proto comments], so plain summation nets it out.

SAM sizing note [V, memory note `project_sam_mcp_workflow_tools.md`]: an MCP tool response over 2048 bytes becomes an artifact, and its fields stop resolving in workflow nodes. The decoded receipt (8.7 KB) and even a normalized 2-3 line sale (about 1.8 KB + 0.7 KB per line) exceed that. Decode and normalize deterministically outside the LLM, for example in a bridge or micro-integration that publishes `normalized sale`, and give workflow nodes only a compact summary: receipt_id, store, and per line `{article_id, sold_units, unit_price, promotion_ids}` [A, design].

---

## 7. Simulator fidelity checklist (swap to the GEBIT lab later)

- Emit `PurchaseTransactionClosed` with `serializedReceiptFormat="PROTOBUF"`, `serializedReceiptContent` = base64(Any(Receipt)) and `serializedReceiptVersion`. Build the Receipt with the `receipt-api-2.13.0.pb` descriptor; protobuf `message_factory` does this without codegen, as `decode_receipt.py` shows. On swap the decoder stays the same and only the event source changes.
- Fill the same ids that link the receipt to the fine-grained events:
  - `receipt_id` = `purchaseTransactionId`
  - position `createdAt` = PositionAdded `createdAt`
  - `fiscalTransactionId` = FiscalTransactionAssigned
  - `closedAt` = `finalizedAt`
- Use Purchase-API types (BDecimal, flat OffsetTimestamp, list of Tax) in the fine-grained events and Receipt-API types (Decimal string, nested OffsetTimestamp, tax map) inside the receipt.
- Use `location` `Root.DE.<co>.<store>.<till>` and `DE_SerialNoTill` = location. Use a `receipt_number` with the same 29-digit shape. Its internal structure appears to hold country, company, store, till, a yyMMdd date and an 8-digit counter (`gebit-purchase-api.md` 3.2) [A]; ask GEBIT. Our simulator uses a shorter 17-digit form, `<store><till><yyMMdd><6-digit sequence>`.
- Add the loyalty `earned_amounts` with `positionFractions` even for anonymous sales, as GEBIT does, and `checkout_coupons[]` for the next-visit coupon. In simulation the agent's coupon can live there. Live, it lives on the monitor until GEBIT confirms a native path.
- Use extension properties as the correlation hook (e.g. `agentProposalId`, `priceChangeId` on the position) [A].

---

## 8. Open questions for GEBIT

1. Can we get the Receipt API **2.14** protos/descriptor (the event says `2.14.0-I114`)? What compatibility guarantees exist between minor versions?
2. Which events do they recommend for downstream analytics: `PurchaseTransactionFinalized` or `PurchaseTransactionClosed`? Do void receipts also arrive as Closed with `receipt_reference_type=VOID`? Do cancelled receipts carry the full basket?
3. What values can `receipt_type`, `serialized_receipt_format`, `price_source` (what does `freezePrice` mean?) and `capturing_information.input_method/input_type` take?
4. What is the semantics of `location` (`Root.DE.999.101.01`), and what is the structure of `receipt_number`?
5. What is the tax class mapping (here `C` = 19%)? Is it tenant specific?
6. Is the scanned GTIN always in `capturing_information.input_value`? How does a GTIN map to `article_id`?
7. Price change: after the article master price change event, when does the next `AddArticle` use the new price? Which `price_source` value results? Can the price change carry an id that reaches the receipt, for attribution?
8. Checkout coupons: which component creates `checkout_coupons[]`? Can an external system (the agent) trigger or define one? Is `print_content` printed?
9. Are `extension_properties` ever printed? Is `AddExtensionProperties` allowed while `IN_PAYMENT`?
10. Fiscalization in the demo lab: is it always the FCC simulator (`++FCC+SIMULATOR++`)? Is there a training mode (`AVTraining`)? What wording does GEBIT use on demo receipts at trade shows?
11. Loyalty in the lab: is there a loyalty system simulator (program `POINTS-ID`, promotion `promotion-base-points`)? What is the earn rule?
12. Which commands create `Receipt.approvals[]`? A price override approved by a supervisor would make a strong talking point for the approval story.
