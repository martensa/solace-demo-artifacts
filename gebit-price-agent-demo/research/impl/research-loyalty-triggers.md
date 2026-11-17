# Simulated Loyalty Service (GEBIT style) and price-change trigger catalogue

Track: loyalty service "analog zu GEBIT" plus a catalogue of different
price-change triggers for the POS simulator. EuroCIS 2027 showcase
"Preis- und Aktionsagent mit Freigabe" (GEBIT + Solace Agent Mesh).
Written 2026-11-10. Binding owner constraints applied: POS simulator
raises GEBIT Purchase API events as SAM triggers, SAM Notifications /
HITL / Workflows / Agents / Multimodal, GEBIT message format, gRPC
endpoints, simulated loyalty service, everything in Postgres, AKS
target, MHD scenario dropped, price changes with several triggers,
uniform shelf price, reductions only, no legal review (but keep it
correct).

Method: read-only. GEBIT protos (`SP/gebit/`) and descriptor sets
(`~/Downloads/Gebit/*.pb`, opened as data only, never copied), the
research files in `gebit-price-agent-demo/research/`, DESIGN.md, the
SAM 2.542.1 docs/skills in the scratchpad, and the sibling track
reports `impl/research-hitl.md`, `impl/research-multimodal.md`,
`impl/research-grpc.md`, `impl/research-aks.md` (aligned with them).
No lab, broker, DB or repo change. Python ran with `-I`.

Legend: **[V]** verified (file:line, command, or validation run named),
**[A]** assumption or design decision, **[G0]** must be proven in a
Gate-0 spike. `SP` = `<scratchpad>`,
`P/` = `SP/gebit/purchase/de/gebit/rp/purchase/purchase/v2/`,
`R/` = `SP/gebit/receipt/de/gebit/rp/receipt/receipt/v2/datatype/`,
`IMPL` = `SP/impl`.

Artifacts produced in this track (all local, nothing applied):

- `IMPL/loyalty-proto/de/showcase/loyalty/v1/**` - 11 `.proto` files
  (1,423 lines with comments), compiled with `protoc` 34.1 into
  `IMPL/loyalty-tools/showcase-loyalty-v1.pb` [V].
- `IMPL/loyalty-sql/10-loyalty-schema.sql` (22 statements) and
  `20-loyalty-seed.sql` (10 statements), parsed with libpg_query
  (pglast 8.7) [V syntax only, not executed].
- `IMPL/loyalty-tools/examples/*.json` - 14 example payloads, 7 in
  GEBIT format (validated against purchase-api 2.50.0 / receipt-api
  2.13.0) and 7 in our format (validated against our descriptor set),
  14/14 OK (`validate_examples.py`, output in `validate_output.txt`) [V].
- `IMPL/loyalty-tools/calc_triggers.py` and `calc_output.txt` - all
  trigger numbers recomputed with the DESIGN.md 8.1 formulas; TR1
  reproduces DESIGN S1 exactly (8,67 -> 6,89, +8,7 EUR, 24,0 %) [V].

---

## 0. TL;DR

1. **GEBIT has no loyalty service API** [V]. The 2.50.0 descriptor set
   has exactly one service (`PurchaseTransactionService`, 106 RPCs);
   loyalty exists only as 8 POS commands, 10 POS events and datatypes
   inside the purchase transaction and the receipt. The loyalty system
   behind it (membership lookup, coupon validation, points, checkout
   coupons, purchase report) is internal and undocumented. Our simulated
   service fills exactly that gap.
2. **Our service** = gRPC `de.showcase.loyalty.v1.service.LoyaltyService`
   (12 unary RPCs, GEBIT conventions: command `Header` with
   originator/approver, `BDecimal`/`Money`, `Metadata.offset`,
   `extension_properties`, rich `ErrorMessage`), events as proto3 JSON
   with `@type` on `showcase/loyalty/v1/{category}/{Event}/{country}/{company}/{store}/{membershipId}`,
   data in Postgres schema `loyalty` (DB `gpos`), port 50052 (aligned
   with the AKS track) [V compiled, A design].
3. **Role split mirrors GEBIT**: the POS simulator asks the loyalty
   service while it processes `AssignLoyaltyMembership`,
   `AssignLoyaltyCoupon` / `ApplyAnonymousCoupon` and the closing; SAM
   never talks gRPC directly but through the engine's MCP tools
   (`get_member_profile`, `get_offers`, `issue_coupon`,
   `redeem_coupon`); the LLM never sees a coupon code.
4. **Four fictional persona cards** named after shopping occasions
   (Kaffeepause, Filmabend, Badezeit, Nur Basis) plus a guest card. No
   names, age, sex, family, occupation, income, health, diet, location;
   tags only from an allowlist enforced by a foreign key; one card
   without profiling consent shows the consent gate.
5. **Seven triggers** (TR1-TR7): slow seller (Ente 8,67 -> 6,89),
   overstock after a delivery advice (Kaffeepads 4,99 -> 3,99),
   competitor flyer photo (Espresso 7,99 -> 6,99, multimodal), basket
   affinity tied offer (Guacamole 2,09 with chips), member coupon
   (Cantuccini 1,60 for "Kaffeepause"), season end (Valentins-Pralinen
   6,99 -> 4,89), guardrails without proposal (promotion collision,
   price-bound book). Four change the uniform shelf price (all need a
   human click), two are coupons (catalogue, no click), one blocks.
6. **HITL aligned with the HITL track**: approval is the gated
   `type: tool` node in a tool-only approval workflow (needs
   `SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME=true`, G0-19); agent-level
   tool approval is a fail-safe denial for event-triggered runs, so no
   loyalty tool that needs approval is attached to an agent.
7. **PAngV 30-day rule kept exactly as in DESIGN 8.1** for announced
   shelf reductions; coupons are individual reductions (section 11 (4)
   no. 1) and tied offers are outside Art. 6a, so neither shows a 30-day
   line. New finding: booth-applied promotions must never enter the
   `ref30` history, or the second visitor's "-20 %" becomes impossible
   (A07).

---

## 1. Loyalty in GEBIT's material

### 1.1 Commands (all on `PurchaseTransactionService`, all return `Empty`) [V]

Source `P/command/loyalty_command.proto`, RPCs at
`P/service/purchase_transaction_service.proto:176-193`. Every command
has `header` (1, `command.Header{trace_id, originator, approver}`),
`purchase_transaction_id` (2) and `extension_properties`.

| Command | Specific fields | Event |
|---|---|---|
| `AssignLoyaltyMembership` | `membership_identification_value` (3, scanned barcode or membership number the cashier keys in), `capturing_information` (5) | `LoyaltyMembershipAssigned` |
| `VoidLoyaltyMembership` | `membership_position_id` (3) | `LoyaltyMembershipVoided` |
| `AssignLoyaltyCoupon` | `coupon_identification_value` (3), `capturing_information` (5) | `LoyaltyCouponAssigned` or `UnverifiedLoyaltyCouponAssigned` (no membership yet) |
| `VoidLoyaltyCoupon` | `membership_position_id` (3), `coupon_position_id` (4) | `LoyaltyCouponVoided` |
| `VoidUnverifiedLoyaltyCoupon` | `coupon_position_id` (3) | `UnverifiedLoyaltyCouponVoided` |
| `ApplyAnonymousCoupon` | `prefix` (3), `promotion_code` (4), `capturing_information` (6) | `AnonymousCouponApplied` |
| `RemoveAnonymousCoupons` | filter `prefix` (3), `promotion_code` (4), `extension_property` (5) | `AnonymousCouponsRemoved` |
| `VoidAnonymousCoupon` | `coupon_position_id` (3) | `AnonymousCouponVoided` |

Related, not loyalty-specific: `AssignCustomer{customer: CustomerData}`
(name, addresses, VAT id; we never use it, guardrail C06),
`ApplyArticlePositionPromotion{captured_promotion.promotion_code}`
(the discount-sticker case), and the query `GetPurchaseTransaction`, which is
the only way to read membership details during a basket [V].

### 1.2 Events (`P/event/loyalty_event.proto`) [V]

Common: `header.event_timestamp`, `metadata{offset, creation_timestamp, trace_id}`,
`purchase_transaction_id`, `purchase_transaction_status`,
`pricing_information` (mandatory by comment, but GEBIT's samples omit
such fields in other events, purchase research 3.6), `extension_properties`.

| Event | Specific fields | Async option |
|---|---|---|
| `LoyaltyMembershipAssigned` | `membership_position_id`, `capturing_information`, `payment_session_sums` | yes |
| `LoyaltyMembershipVoided` | `membership_position_id` | yes |
| `LoyaltyCouponAssigned` | `membership_position_id`, `coupon_position_id`, `capturing_information`, `payment_session_sums` | yes |
| `LoyaltyCouponVoided` | `membership_position_id`, `coupon_position_id` | yes |
| `UnverifiedLoyaltyCouponAssigned` / `Voided` / `Removed` | `coupon_position_id` (+ capturing on Assigned) | yes |
| `AnonymousCouponApplied` | `prefix`, `promotion_code`, `coupon_position_id`, `capturing_information`, `payment_session_sums` | yes |
| `AnonymousCouponsRemoved` | `removed_anonymous_coupons[]` | **no** |
| `AnonymousCouponVoided` | `coupon_position_id`, `payment_session_sums` | **no** |

Payment-side, also coupon-related: `CouponPaymentPositionCreated`
(industrial coupon cashed as payment) and
`PromotionPaymentPositionsCreated` [V descriptor scan].

**`LoyaltyMembershipAssigned` carries no `membership_id`, no program,
no balance and no coupons** [V]. A consumer must call
`GetPurchaseTransaction` or keep the card value from the command.

### 1.3 Datatypes

Purchase side (`P/datatype/loyalty_datatype.proto`) [V]:

- `Loyalty{anonymous_coupons[], loyalty_memberships[] (3), unverified_loyalty_coupons[] (4)}`
  on `PurchaseTransaction.loyalty` (field 20).
- `AnonymousCoupon{prefix, promotion_code, extension_properties, value: BDecimal (amount of an industrial price-reduction coupon), description, coupon_position_id, voided, capturing_information, applied}`.
- `LoyaltyMembership{membership_position_id, membership_identification_value, membership_id, program_id, program_name, optional customer_id (absent for anonymous memberships), anonymous (15), voided, verified (meaningful also while the loyalty system is offline), coupons[], receipt_content: FormattedContent, membership_preferences[] (e.g. digital receipt wanted), extension_properties, capturing_information, accounts[]}`.
- `LoyaltyCoupon{coupon_position_id, optional coupon_identification_value (empty if added with the membership), coupon_id, optional coupon_description, from_membership, applied, voided, extension_properties, capturing_information}`.
- `LoyaltyAccount{account_id, account_type, optional account_description, account_currency_name, account_balance: BDecimal (balance prior to this purchase), extension_properties}`.
- `UnverifiedLoyaltyCoupon{coupon_position_id, coupon_identification_value, voided, extension_properties, capturing_information}`.
- Promotion link: `PromotionActionTrigger{promotion_id, oneof anonymous_coupon{coupon_position_id} | loyalty_membership{loyalty_membership_position_id, loyalty_coupon_position_id} | unqualified}` (`P/datatype/common_datatype.proto:112-159`), used by `PromotionPaymentPosition.trigger`. Position discounts carry `BaseDiscount{discount_id, discount_type ABSOLUTE|RELATIVE|NEW_PRICE, description, amount, percentage, reason_code}`; the receipt adds `promotion_id` (`R/basket_datatype.proto:731`).

Receipt side (`R/loyalty_datatype.proto`) [V]:

- `Loyalty{anonymous_coupons[], loyalty_memberships[], loyalty_purchase_result}`.
- Differences to the purchase side: `LoyaltyMembership.accounts` is a
  **map** keyed by account type; `LoyaltyAccount` has
  `account_currency: LoyaltyEntityDescriptor` and
  `account_balance_before_purchase: basic.Decimal{value: string}`.
- `LoyaltyPurchaseResult{checkout_coupons[], earned_amounts[] (2), burned_amounts[] (4), deferred_purchase_report_request: Any (3, report for the loyalty system, sent once the purchase transaction is closed)}`.
- `CheckoutCoupon{application: BenefitApplicationAttributes, coupon_id (3), print_content: FormattedContent (4)}`.
- `EarnCurrency` / `BurnCurrency{application, account, currency, earned_amount|burned_amount: Decimal, position_fractions[]{position_id, item_count, fraction_amount}}`;
  the earned amount is what the customer got, or would get as a member.
- `BenefitApplicationAttributes{program{id,name}, optional membership_id, optional benefit_id, optional promotion_id, reported, extension_properties}`.

Sample facts [V `simpleSale.json`]: anonymous sale of the Ente
(8,67 EUR) earns `4.00` points, program `POINTS-ID`/"POINTS", account
`POINTS-ACCOUNT-ID`, currency `POINTS-CURRENCY-ID`/"Points", promotion
`promotion-base-points`, `reported: true`, no membership. The earn rule
"1 point per full 2 EUR" reproduces it (floor(8,67/2) = 4) [A, rule
not documented].

### 1.4 What is NOT in GEBIT's material [V by descriptor scan and grep]

1. No loyalty service, no loyalty system interface (SPI) and no
   connector contract. Both descriptor sets contain only
   `PurchaseTransactionService`; "LoyaltyService"/"LoyaltySystem" occur
   0 times in both HTML docs; "loyalty system" occurs only in field
   comments.
2. No member, profile, enrolment, consent, preference-tag or
   purchase-history API.
3. No points query, no burn command, no points events. Earn/burn and
   checkout coupons exist only in the receipt.
4. No coupon issuing, coupon catalogue, coupon validity or
   single-use enforcement; no command that injects a `CheckoutCoupon`
   or earn/burn into a transaction.
5. No definition of which coupon types are "from membership" and
   whether they emit `LoyaltyCouponAssigned` automatically [A: probably
   yes].
6. `deferred_purchase_report_request` is an opaque `Any`; the report
   format is unknown.
7. The extracted proto sources lack
   `de/gebit/rp/protobuf/{options,basic,formatted_content}`; only the
   `.pb` sets contain them.

**Implication:** in GEBIT's architecture our service plays the role of
the "loyalty system" that the purchase service consults. In simulation
our POS simulator calls it; in the GEBIT lab only GEBIT can wire their
purchase service to it (question L1 in section 5).

---

## 2. Our simulated Loyalty Service

### 2.1 Role and boundaries

```text
 Kasse UI ── gRPC ──> gpos-pos (Purchase API sim, :50051) ── proto3 JSON ──> Solace gebit/rp/purchase/v2/...
                           │ ResolveMembership / ResolveCoupon /                     │ (R1: all booth-till events)
                           │ CalculatePurchaseResult / ReportPurchase                v
                           v                                                SAM gpos-pos-event, approval wf
                      gpos-loyalty (:50052 gRPC, health, reflection)                 │ MCP tools
                           │  Postgres schema loyalty  ── outbox ──> Solace showcase/loyalty/v1/...
                           ^                                                         │
                           └──────────── gRPC (engine facade) <── gpos-engine (:8765 MCP)
```

- 4th deployment `gpos-loyalty` (Python, grpcio + reflection + health,
  same scaffold as the POS spike in `research-grpc.md`; our own `.pb`
  may live in the repo because it is ours).
- The engine is the only SAM-facing component (MCP facade). The
  loyalty service never speaks MCP, like a vendor system would not.
- Postgres: schema `loyalty` in DB `gpos`, role `gpos_loyalty`; the
  engine role has no grant on it (service boundary) [A].
- Exposure: ClusterIP `gpos-loyalty:50052`; NGINX ingress
  `backend-protocol: GRPC` with TLS as `loyalty-grpc.<domain>` in lab
  and AKS (AKS track section 3) [A]. Server reflection on, so grpcurl
  and Postman work without local files.

### 2.2 GEBIT conventions we copy (and where we deviate)

| Convention | GEBIT [V] | Ours |
|---|---|---|
| Package layout | `de.gebit.rp.purchase.purchase.v2.{command,datatype,event,query,service}` | `de.showcase.loyalty.v1.{command,datatype,event,query,service}` |
| Command header | `Header{trace_id, originator, approver}` | identical shape; `approver` mandatory for `IssueSpecialCoupon` |
| Command result | `Empty` or an id, outcome as events | same (`CouponId`, `Empty`) |
| Query shape | `trace_id` first, no header | same |
| Decimal / money | `BDecimal{scale, int_val}`, `Money{currency, amount}` | identical field names and numbers (wire and JSON compatible) |
| Time | own `Timestamp{seconds,nanos}`, `OffsetTimestamp{+offset}` | identical |
| Event envelope | `Header{event_timestamp}` + `Metadata{offset, creation_timestamp, trace_id}` | identical; offset per aggregate (member or coupon) |
| Extension points | `repeated Property extension_properties` everywhere | same, keys `showcase.*` |
| Errors | gRPC rich error model, `ErrorMessage{error_code, error_message, error_details[], trace_id}` | same, codes `LOY-0xx` (2.4) |
| Enum style | `DISCOUNT_TYPE_UNSPECIFIED = 0` prefix style | same; `DiscountType` values identical |
| Async marker | custom option `async_message_set` (ext 52548) | not copied (would need GEBIT's options proto); comment only |

No GEBIT file is imported; our types are self-contained copies of the
shape [V: `protoc` compiled without any GEBIT path]. Keep the package
local until GEBIT agrees, as DESIGN decision 6 says for all GEBIT
details [A].

### 2.3 Proto sketch (generated from the compiled descriptor set)

Full commented sources: `IMPL/loyalty-proto/de/showcase/loyalty/v1/`.
The compact form below is produced by `IMPL/loyalty-tools/compact.py`
from `showcase-loyalty-v1.pb`, so it cannot drift from what compiles.
`java_*` options and comments omitted.

```proto
// command/common_command.proto  (package de.showcase.loyalty.v1.command)
message AuthorizationInformation { string identity_id = 1; string details = 2; }
message Header { string trace_id = 1; AuthorizationInformation originator = 2;
    AuthorizationInformation approver = 3; }

// datatype/common_datatype.proto  (package de.showcase.loyalty.v1.datatype)
message Metadata { int64 offset = 1; Timestamp creation_timestamp = 2; string trace_id = 3; }
message BDecimal { int32 scale = 1; int64 int_val = 2; }
message Money { string currency = 1; BDecimal amount = 2; }
message Timestamp { int64 seconds = 1; int32 nanos = 2; }
message OffsetTimestamp { int64 seconds = 1; int32 nanos = 2; int32 offset = 3; }
message Property { string key = 1; TypedValue typed_value = 2; }
message TypedValue { reserved 5-10; oneof type { string string_value = 1; sint64 integer_value = 2;
    BDecimal decimal_value = 3; bool bool_value = 4; Money money_value = 11; string json_value = 12 } }
message CapturingInformation { string input_method = 1; string input_type = 2;
    string input_value = 3; OffsetTimestamp input_time = 4; }
message ErrorMessage { string error_code = 1; string error_message = 2;
    repeated ErrorDetails error_details = 3; string trace_id = 4; }
message ErrorDetails { string key = 1; string value = 2; }
message LoyaltyEntityDescriptor { string id = 1; string name = 2; }

// datatype/loyalty_enum.proto
enum MembershipStatus { MEMBERSHIP_STATUS_* : UNSPECIFIED | ACTIVE | BLOCKED | UNKNOWN }
enum Salutation { SALUTATION_* : UNSPECIFIED | FORMAL | INFORMAL }
enum OfferKind { OFFER_KIND_* : UNSPECIFIED | PERSONAL_COUPON | TIED_OFFER | CHECKOUT_COUPON |
    SPECIAL_COUPON }
enum DiscountType { DISCOUNT_TYPE_* : UNSPECIFIED | ABSOLUTE | RELATIVE | NEW_PRICE }
enum CouponStatus { COUPON_STATUS_* : UNSPECIFIED | ISSUED | REDEEMED | VOIDED | EXPIRED }
enum IssueChannel { ISSUE_CHANNEL_* : UNSPECIFIED | RULE | AGENT | HUMAN_APPROVED | CHECKOUT }
enum ApprovalMode { APPROVAL_MODE_* : UNSPECIFIED | NONE | HUMAN }
enum TransactionType { TRANSACTION_TYPE_* : UNSPECIFIED | SALE | VOID }
enum CouponResolutionResult { COUPON_RESOLUTION_RESULT_* : UNSPECIFIED | VALID | UNKNOWN | EXPIRED |
    ALREADY_REDEEMED | WRONG_MEMBER | NOT_APPLICABLE }

// datatype/loyalty_datatype.proto
message CouponId { string coupon_id = 1; string coupon_identification_value = 2; }
message ConsentFlags { bool offers = 1; bool profiling = 2; bool digital_receipt = 3;
    string policy_version = 4; OffsetTimestamp changed_at = 5; }
message LoyaltyAccount { string account_id = 1; string account_type = 2;
    optional string account_description = 3; string account_currency_name = 4;
    BDecimal account_balance = 5; repeated Property extension_properties = 6; }
message MemberCoupon { string coupon_id = 1; string coupon_identification_value = 2;
    optional string coupon_description = 3; string offer_id = 4; CouponStatus status = 5;
    OffsetTimestamp valid_from = 6; OffsetTimestamp valid_to = 7; DiscountType discount_type = 8;
    BDecimal discount_value = 9; Money max_discount = 10; optional string target_article_number = 11;
    string promotion_id = 12; repeated Property extension_properties = 13; }
message MembershipResolution { string membership_identification_value = 1; string membership_id = 2;
    string program_id = 3; string program_name = 4; optional string customer_id = 5; bool anonymous = 6;
    bool verified = 7; MembershipStatus status = 8; repeated MemberCoupon coupons = 9;
    repeated LoyaltyAccount accounts = 10; repeated Property membership_preferences = 11;
    repeated string receipt_text_lines = 12; repeated Property extension_properties = 13; }
message CouponResolution { CouponResolutionResult result = 1; MemberCoupon coupon = 2;
    optional string membership_id = 3; string prefix = 4; string promotion_code = 5; }
message CategoryFrequency { string category = 1; int32 purchases_8w = 2; int32 days_since_last = 3; }
message MemberProfile { string membership_id = 1; string persona_label = 2; Salutation salutation = 3;
    repeated string preference_tags = 4; ConsentFlags consent = 5; BDecimal points_balance = 6;
    repeated CategoryFrequency history = 7; int32 open_coupons = 8; bool history_used = 9; }
message Offer { string offer_id = 1; OfferKind kind = 2; optional string target_article_number = 3;
    optional string condition_article_number = 4; DiscountType discount_type = 5;
    BDecimal discount_value = 6; Money max_discount = 7; Money min_basket = 8; int32 valid_days = 9;
    bool in_catalogue = 10; ApprovalMode approval = 11; string prefix = 12; string promotion_code = 13;
    string promotion_id = 14; string text_key = 15; repeated string match_tags = 16; }
message OfferCandidate { string slot = 1; Offer offer = 2; BDecimal score = 3; Money price_before = 4;
    Money price_after = 5; int32 pct_shown = 6; repeated string why_facts = 7; bool blocked = 8;
    string blocked_rule = 9; }
message EligibleOffers { repeated OfferCandidate candidates = 1; string recommended_slot = 2;
    bool personalised = 3; }
message MemberCoupons { repeated MemberCoupon coupons = 1; }
message BasketLine { string position_id = 1; string article_id = 2; string article_number = 3;
    string category = 4; int32 item_count = 5; Money effective_value = 6; bool effectual = 7;
    bool promotion_active = 8; }
message AppliedCoupon { string coupon_position_id = 1; string coupon_identification_value = 2;
    string prefix = 3; string promotion_code = 4; bool applied = 5; bool from_membership = 6;
    Money discount_granted = 7; }
message PurchaseSummary { string purchase_transaction_id = 1; string receipt_number = 2;
    string location = 3; TransactionType transaction_type = 4; OffsetTimestamp closed_at = 5;
    optional string membership_id = 6; repeated BasketLine lines = 7; Money total = 8;
    repeated AppliedCoupon coupons = 9; optional string referenced_purchase_transaction_id = 10;
    repeated Property extension_properties = 11; }
message BenefitApplicationAttributes { LoyaltyEntityDescriptor program = 1;
    optional string membership_id = 2; optional string benefit_id = 3; optional string promotion_id = 4;
    bool reported = 5; repeated Property extension_properties = 6; }
message BenefitApplicationPositionFraction { string position_id = 1; sint32 item_count = 2;
    BDecimal fraction_amount = 3; }
message CheckoutCoupon { reserved 2; BenefitApplicationAttributes application = 1; string coupon_id = 3;
    repeated string print_text_lines = 4; string barcode_value = 5; }
message EarnCurrency { BenefitApplicationAttributes application = 1; LoyaltyEntityDescriptor account = 2;
    LoyaltyEntityDescriptor currency = 3; BDecimal earned_amount = 4;
    repeated BenefitApplicationPositionFraction position_fractions = 5; }
message BurnCurrency { BenefitApplicationAttributes application = 1; LoyaltyEntityDescriptor account = 2;
    LoyaltyEntityDescriptor currency = 3; BDecimal burned_amount = 4;
    repeated BenefitApplicationPositionFraction position_fractions = 5; }
message PurchaseResult { reserved 3; repeated CheckoutCoupon checkout_coupons = 1;
    repeated EarnCurrency earned_amounts = 2; repeated BurnCurrency burned_amounts = 4; }

// command/loyalty_command.proto
message IssueCoupon { Header header = 1; string membership_id = 2; string offer_id = 3;
    datatype.IssueChannel channel = 4; optional string purchase_transaction_id = 5;
    optional string proposal_id = 6; optional string display_text = 7;
    repeated datatype.Property extension_properties = 8; }
message IssueSpecialCoupon { Header header = 1; string membership_id = 2; string target_article_number = 3;
    datatype.DiscountType discount_type = 4; datatype.BDecimal discount_value = 5; int32 valid_days = 6;
    string reason_code = 7; string proposal_id = 8; optional string display_text = 9;
    repeated datatype.Property extension_properties = 10; }
message VoidCoupon { Header header = 1; string coupon_id = 2; string reason_code = 3;
    repeated datatype.Property extension_properties = 4; }
message ReportPurchase { Header header = 1; datatype.PurchaseSummary purchase = 2;
    repeated datatype.Property extension_properties = 3; }
message ChangeConsent { Header header = 1; string membership_id = 2; datatype.ConsentFlags consent = 3;
    repeated datatype.Property extension_properties = 4; }
message ResetDemoState { Header header = 1; string visit_id = 2; bool full_day_reset = 3; }

// query/loyalty_query.proto
message ResolveMembership { string trace_id = 1; string membership_identification_value = 2;
    string purchase_transaction_id = 3; string location = 4; optional string membership_position_id = 5;
    datatype.CapturingInformation capturing_information = 6; }
message ResolveCoupon { string trace_id = 1; string coupon_identification_value = 2;
    optional string membership_id = 3; string purchase_transaction_id = 4;
    repeated datatype.BasketLine basket = 5; }
message GetMemberProfile { string trace_id = 1; string membership_id = 2; }
message ListEligibleOffers { string trace_id = 1; optional string membership_id = 2;
    string purchase_transaction_id = 3; repeated datatype.BasketLine basket = 4; int32 max_candidates = 5;
    datatype.OfferKind kind = 6; }
message ListMemberCoupons { string trace_id = 1; string membership_id = 2; bool include_inactive = 3; }
message CalculatePurchaseResult { string trace_id = 1; datatype.PurchaseSummary purchase = 2; }

// event/common_event.proto, membership_event.proto, coupon_event.proto, account_event.proto
message Header { datatype.Timestamp event_timestamp = 1; }
message MembershipResolved { Header header = 1; datatype.Metadata metadata = 2; string membership_id = 3;
    string program_id = 4; bool verified = 5; bool anonymous = 6; string purchase_transaction_id = 7;
    string location = 8; string persona_label = 9; int32 open_coupons = 10;
    repeated datatype.Property extension_properties = 11; }
message MembershipResolutionFailed { Header header = 1; datatype.Metadata metadata = 2;
    string identification_value_hash = 3; string purchase_transaction_id = 4; string location = 5;
    string reason_code = 6; }
message ConsentChanged { Header header = 1; datatype.Metadata metadata = 2; string membership_id = 3;
    datatype.ConsentFlags consent = 4; repeated datatype.Property extension_properties = 5; }
message CouponIssued { Header header = 1; datatype.Metadata metadata = 2; string coupon_id = 3;
    optional string membership_id = 4; string offer_id = 5; datatype.OfferKind kind = 6;
    datatype.IssueChannel channel = 7; datatype.OffsetTimestamp valid_to = 8;
    datatype.DiscountType discount_type = 9; datatype.BDecimal discount_value = 10;
    optional string target_article_number = 11; optional string purchase_transaction_id = 12;
    optional string proposal_id = 13; optional string approver_ref = 14;
    repeated datatype.Property extension_properties = 15; }
message CouponRedeemed { Header header = 1; datatype.Metadata metadata = 2; string coupon_id = 3;
    optional string membership_id = 4; string purchase_transaction_id = 5; string coupon_position_id = 6;
    datatype.Money discount_granted = 7; repeated datatype.Property extension_properties = 8; }
message CouponVoided { Header header = 1; datatype.Metadata metadata = 2; string coupon_id = 3;
    optional string membership_id = 4; string reason_code = 5; }
message CouponExpired { Header header = 1; datatype.Metadata metadata = 2; string coupon_id = 3;
    optional string membership_id = 4; }
message PointsEarned { Header header = 1; datatype.Metadata metadata = 2; string membership_id = 3;
    string account_id = 4; datatype.BDecimal amount = 5; datatype.BDecimal balance_after = 6;
    string purchase_transaction_id = 7; string promotion_id = 8;
    repeated datatype.Property extension_properties = 9; }
message PointsReversed { Header header = 1; datatype.Metadata metadata = 2; string membership_id = 3;
    string account_id = 4; datatype.BDecimal amount = 5; datatype.BDecimal balance_after = 6;
    string purchase_transaction_id = 7; string referenced_purchase_transaction_id = 8; }

// service/loyalty_service.proto  (package de.showcase.loyalty.v1.service)
service LoyaltyService {
  // POS side: what GEBIT's purchase service would ask a loyalty system
  rpc ResolveMembership(query.ResolveMembership) returns (datatype.MembershipResolution);
  rpc ResolveCoupon(query.ResolveCoupon) returns (datatype.CouponResolution);
  rpc CalculatePurchaseResult(query.CalculatePurchaseResult) returns (datatype.PurchaseResult);
  rpc ReportPurchase(command.ReportPurchase) returns (google.protobuf.Empty);
  // Engine side: behind the MCP tools
  rpc GetMemberProfile(query.GetMemberProfile) returns (datatype.MemberProfile);
  rpc ListEligibleOffers(query.ListEligibleOffers) returns (datatype.EligibleOffers);
  rpc ListMemberCoupons(query.ListMemberCoupons) returns (datatype.MemberCoupons);
  rpc IssueCoupon(command.IssueCoupon) returns (datatype.CouponId);
  rpc IssueSpecialCoupon(command.IssueSpecialCoupon) returns (datatype.CouponId);
  rpc VoidCoupon(command.VoidCoupon) returns (google.protobuf.Empty);
  // Operator side
  rpc ChangeConsent(command.ChangeConsent) returns (google.protobuf.Empty);
  rpc ResetDemoState(command.ResetDemoState) returns (google.protobuf.Empty);
}
```

Design notes:

- `MembershipResolution` mirrors GEBIT's purchase `LoyaltyMembership`
  field by field (except `receipt_content`, which the POS maps from
  `receipt_text_lines` to `FormattedContent`). `PurchaseResult`,
  `CheckoutCoupon`, `EarnCurrency` mirror the receipt types.
- `CalculatePurchaseResult` is a pure query. Checkout-coupon ids are
  derived deterministically (`CPN-` + base32(HMAC(key, tx_id|offer_id))[:8]),
  so a retried closing gets the same ids, and `ReportPurchase` creates
  the rows. Cancelled baskets are never reported, so their coupons never
  exist (finality, C03) [A].
- The POS reports during `IN_CLOSING` (synchronous, idempotent per
  `purchase_transaction_id`) and writes `reported: true`, matching the
  GEBIT sample. If the loyalty service is down, `reported: false` and
  the outbox retries; the till never blocks [A].
- `coupon_identification_value` is a bearer secret: returned only to
  the POS (resolve) and to the engine (issue), never in events and
  never to an agent.
- Anonymous purchases still get `earned_amounts` without
  `membership_id` (what a member would have earned), as in GEBIT's
  sample. The monitor can show "Mit Karte haetten Sie 4 Punkte".

### 2.4 Errors (rich error model, `ErrorMessage` as status detail)

| Code | gRPC status | When |
|---|---|---|
| LOY-001 UNKNOWN_CARD | NOT_FOUND | card value unknown (POS still assigns, `verified=false`) |
| LOY-002 MEMBERSHIP_BLOCKED | FAILED_PRECONDITION | blocked card |
| LOY-010 COUPON_NOT_FOUND | NOT_FOUND | unknown coupon value |
| LOY-011 COUPON_EXPIRED | FAILED_PRECONDITION | after `valid_to` |
| LOY-012 COUPON_ALREADY_REDEEMED | ALREADY_EXISTS | second use |
| LOY-013 COUPON_WRONG_MEMBER | PERMISSION_DENIED | member coupon on another card |
| LOY-020 OFFER_NOT_IN_CATALOGUE | INVALID_ARGUMENT | `IssueCoupon` with a non-catalogue offer |
| LOY-021 VALUE_CAP_EXCEEDED | INVALID_ARGUMENT | > 30 % or > max discount (catalogue), > 50 % or below net cost (special) |
| LOY-022 NO_CONSENT | FAILED_PRECONDITION | personal coupon without `consent.offers` |
| LOY-023 FREQUENCY_LIMIT | RESOURCE_EXHAUSTED | open coupon for the same offer exists |
| LOY-030 APPROVER_REQUIRED | PERMISSION_DENIED | `IssueSpecialCoupon` without `header.approver` |
| LOY-040 STACKING_NOT_ALLOWED | FAILED_PRECONDITION | target article has an active shelf promotion (G03) |
| LOY-050 NOT_ELIGIBLE | FAILED_PRECONDITION | price-bound book, deposit |

### 2.5 Events, topics, delivery

Topic rule, mechanically like GEBIT's raw topics (package minus `de.`,
category = event file stem without `_event`):

```text
showcase/loyalty/v1/{membership|coupon|account}/{EventName}/{country}/{company}/{store}/{membershipId|anonymous}
e.g. showcase/loyalty/v1/coupon/CouponIssued/DE/999/101/M-0001
```

- Store level, not till level: loyalty is a store concern; the till is
  in the payload where relevant (`location`).
- Proto3 canonical JSON with `@type`, persistent, user properties
  `eventType`, `membershipId`, `offset`, `traceId`,
  `apiVersion=showcase-loyalty-1.0.0`, `source=sim`; application
  message id `{aggregateId}:{offset}`; VPN `sam` like all booth topics.
- Transactional outbox (`loyalty.event_outbox`): state change and
  event row commit together, a loop publishes and marks
  `published_at` [A].
- Not subscribed by any SAM entrypoint (the owner's triggers are the
  GEBIT events); consumers are the monitor/BFF and audit.
- Validated example (`examples/ours_evt_CouponIssued.json`, 756 B):

```json
{"@type":"type.googleapis.com/de.showcase.loyalty.v1.event.CouponIssued",
 "header":{"eventTimestamp":{"seconds":"1802871131","nanos":140000000}},
 "metadata":{"offset":"7","creationTimestamp":{"seconds":"1802871131","nanos":118000000},"traceId":"v-0217-0042"},
 "couponId":"CPN-0217-0042","membershipId":"M-0001","offerId":"OFF-CANTUCCINI-30",
 "kind":"OFFER_KIND_PERSONAL_COUPON","channel":"ISSUE_CHANNEL_AGENT",
 "validTo":{"seconds":"1803495600","offset":60},
 "discountType":"DISCOUNT_TYPE_RELATIVE","discountValue":{"scale":2,"intVal":"3000"},
 "targetArticleNumber":"article008","purchaseTransactionId":"5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60",
 "proposalId":"prp-0217-0043",
 "extensionProperties":[{"key":"showcase.samRunId","typedValue":{"stringValue":"wfr-3f9a"}}]}
```

### 2.6 Postgres schema `loyalty` (DDL)

File `IMPL/loyalty-sql/10-loyalty-schema.sql` (parsed OK with
libpg_query/pglast 8.7; not executed: no local Postgres, and lab DB
writes are not allowed in this track). Portable to PostgreSQL 14+;
the AKS track plans Azure Database for PostgreSQL Flexible Server 18.

```sql
create schema if not exists loyalty;
set search_path = loyalty;

create table program (
  program_id text primary key, program_name text not null, display_name text not null,
  account_type text not null, currency_id text not null, currency_name text not null,
  base_promotion_id text not null,
  earn_eur_per_point numeric(6,2) not null check (earn_eur_per_point > 0));   -- 2.00

create table article_ref (                       -- seeded from data/assortment.yaml
  article_number text primary key, article_id text not null unique, name text not null,
  category text not null,
  points_eligible boolean not null default true, -- false: price-bound book, deposit
  coupon_eligible boolean not null default true);

create table tag_vocabulary (                    -- allowlist (C04): only allowed tags exist
  tag text primary key check (tag ~ '^[a-z_]{3,32}$'), label_de text not null);

create table member (
  member_id text primary key,                    -- = LoyaltyMembership.membership_id
  program_id text not null references program,
  customer_ref text unique,                      -- pseudonym; null = anonymous
  persona_key text not null unique, persona_label text not null,
  anonymous boolean not null default false,
  salutation text not null default 'FORMAL' check (salutation in ('FORMAL','INFORMAL')),
  status text not null default 'ACTIVE' check (status in ('ACTIVE','BLOCKED')),
  is_fictional boolean not null default true check (is_fictional),   -- never a real person
  created_at timestamptz not null default now(),
  check (anonymous = (customer_ref is null)));

create table card (
  card_value text primary key,                   -- membership_identification_value
  member_id text not null references member,
  card_type text not null check (card_type in ('PHYSICAL','DIGITAL','GUEST')),
  status text not null default 'ACTIVE' check (status in ('ACTIVE','BLOCKED')),
  issued_at timestamptz not null default now());

create table consent (
  member_id text primary key references member on delete cascade,
  offers boolean not null, profiling boolean not null,
  digital_receipt boolean not null default false, policy_version text not null,
  changed_at timestamptz not null default now(),
  source text not null check (source in ('seed','operator','pos')));

create table member_tag (
  member_id text not null references member on delete cascade,
  tag text not null references tag_vocabulary,
  source text not null check (source in ('EXPLICIT','DERIVED')),
  weight numeric(3,2) not null default 1.00 check (weight > 0 and weight <= 1),
  primary key (member_id, tag));

create table account (
  account_id text primary key, member_id text not null references member,
  program_id text not null references program, account_type text not null,
  balance numeric(12,2) not null default 0 check (balance >= 0),
  unique (member_id, account_type));

create table points_ledger (                     -- append-only; unique = idempotent report
  entry_id bigserial primary key, account_id text not null references account,
  purchase_transaction_id uuid,
  kind text not null check (kind in ('EARN','REVERSAL','ADJUST','EXPIRE','BURN')),
  amount numeric(12,2) not null, balance_after numeric(12,2) not null check (balance_after >= 0),
  promotion_id text, visit_id text, is_seed boolean not null default false,
  created_at timestamptz not null default now(),
  unique (purchase_transaction_id, account_id, kind));

create table offer (
  offer_id text primary key,
  kind text not null check (kind in ('PERSONAL_COUPON','TIED_OFFER','CHECKOUT_COUPON','SPECIAL_COUPON')),
  target_article text references article_ref, condition_article text references article_ref,
  match_tags text[] not null default '{}',
  discount_type text not null check (discount_type in ('RELATIVE','ABSOLUTE','NEW_PRICE')),
  discount_value numeric(8,2) not null check (discount_value > 0),
  max_discount_eur numeric(6,2) not null check (max_discount_eur > 0),
  min_basket_eur numeric(8,2) not null default 0,
  valid_days int not null check (valid_days between 0 and 30),
  in_catalogue boolean not null default true,
  approval text not null default 'NONE' check (approval in ('NONE','HUMAN')),
  prefix text, promotion_code text, promotion_id text not null, text_key text not null,
  priority int not null default 100, active boolean not null default true,
  check (approval = 'HUMAN' or (discount_type <> 'RELATIVE' or discount_value <= 30)),  -- C02 caps
  check (approval = 'HUMAN' or max_discount_eur <= 3.00),
  check (kind <> 'SPECIAL_COUPON' or approval = 'HUMAN'),
  check (kind <> 'TIED_OFFER' or (condition_article is not null and prefix is not null
                                  and promotion_code is not null)));

create table coupon (
  coupon_id text primary key, coupon_code text not null unique,   -- code = bearer secret
  offer_id text not null references offer, member_id text references member,  -- null = anonymous
  status text not null default 'ISSUED' check (status in ('ISSUED','REDEEMED','VOIDED','EXPIRED')),
  discount_type text not null, discount_value numeric(8,2) not null,
  max_discount_eur numeric(6,2) not null,                          -- snapshot at issue
  target_article text references article_ref,
  valid_from timestamptz not null, valid_to timestamptz not null,
  issued_channel text not null check (issued_channel in ('RULE','AGENT','HUMAN_APPROVED','CHECKOUT')),
  issued_in_tx uuid, proposal_id text, approver_ref text, sam_run_id text,
  display_text text check (length(display_text) <= 120), visit_id text,
  issued_at timestamptz not null default now(),
  redeemed_in_tx uuid, redeemed_at timestamptz, discount_granted_eur numeric(6,2),
  check (valid_to > valid_from),
  check ((status = 'REDEEMED') = (redeemed_in_tx is not null)),
  check (issued_channel <> 'HUMAN_APPROVED' or approver_ref is not null));
create unique index coupon_one_open_per_member_offer
  on coupon (member_id, offer_id) where status = 'ISSUED' and member_id is not null;
create index coupon_member_status on coupon (member_id, status);

create table purchase (                          -- reported after closing only
  purchase_transaction_id uuid primary key, member_id text references member,
  receipt_number text not null, location text not null,
  transaction_type text not null check (transaction_type in ('SALE','VOID')),
  referenced_purchase_transaction_id uuid, closed_at timestamptz not null,
  total_eur numeric(10,2) not null, points_earned numeric(12,2) not null default 0,
  visit_id text, is_seed boolean not null default false,
  reported_at timestamptz not null default now(),
  check (transaction_type = 'SALE' or referenced_purchase_transaction_id is not null));

create table purchase_line (                     -- only with consent.profiling = true
  purchase_transaction_id uuid not null references purchase on delete cascade,
  position_id text not null, article_number text not null references article_ref,
  category text not null, item_count int not null, effective_value_eur numeric(10,2) not null,
  primary key (purchase_transaction_id, position_id));

create table membership_assignment (             -- GEBIT position ids per open basket
  purchase_transaction_id uuid not null, member_id text not null references member,
  card_value text not null, membership_position_id text, verified boolean not null,
  resolved_at timestamptz not null default now(),
  primary key (purchase_transaction_id, member_id));

create table event_outbox (
  id bigserial primary key, aggregate_id text not null, aggregate_offset bigint not null,
  event_type text not null, topic text not null, payload jsonb not null,
  created_at timestamptz not null default now(), published_at timestamptz,
  unique (aggregate_id, aggregate_offset));
create index event_outbox_unpublished on event_outbox (id) where published_at is null;

create table audit (
  id bigserial primary key, ts timestamptz not null default now(),
  actor text not null, action text not null, ref text, payload jsonb not null default '{}');

create view member_category_8w as               -- history only with profiling consent (C05)
select m.member_id, l.category,
       count(distinct p.purchase_transaction_id)::int as purchases_8w,
       (current_date - max(p.closed_at)::date)::int   as days_since_last
from member m
join consent c on c.member_id = m.member_id and c.profiling
join purchase p on p.member_id = m.member_id and p.transaction_type = 'SALE'
              and p.closed_at >= now() - interval '56 days'
join purchase_line l on l.purchase_transaction_id = p.purchase_transaction_id
group by m.member_id, l.category;
```

Seed (`20-loyalty-seed.sql`, excerpt): program `POINTS-ID` with 2,00
EUR per point; 10 `article_ref` rows (Kochbuch `points_eligible=false`,
`coupon_eligible=false`); 9 allowed tags; 5 members, 5 cards, consent,
tags, accounts (section 2.7); 6 offers:

| Offer | Kind | Target / condition | Value | Cap | Valid | Approval |
|---|---|---|---|---|---|---|
| OFF-GUAC-30 | TIED_OFFER, code `GPOS:GUAC30` | Guacamole / Tortilla Chips | -30 % | 1,00 EUR | this purchase | none |
| OFF-CANTUCCINI-30 | PERSONAL_COUPON | Cantuccini / Espresso | -30 % | 1,00 EUR | 7 days | none |
| OFF-KAFFEEPADS-30 | PERSONAL_COUPON | Kaffeepads, tag kaffee | -30 % | 2,00 EUR | 7 days | none (campaign activation: human, TR2) |
| OFF-SCHAUMBAD-30 | CHECKOUT_COUPON | Schaumbad / Ente on receipt | -30 % | 1,00 EUR | 14 days | none |
| OFF-WELCOME-10 | CHECKOUT_COUPON | basket >= 10 EUR | -10 % | 2,00 EUR | 14 days | none |
| OFF-SPECIAL | SPECIAL_COUPON (template) | any eligible | <= 50 % | 5,00 EUR | 14 days | human |

Runtime rows carry `visit_id`; `ResetDemoState{visit_id}` voids that
visit's coupons and reverses its points, because the persona cards are
shared by all visitors (without it the frequency rule would block the
second visitor) [A]. Event history is purged per fair day (C08).

### 2.7 Personas (fictional, shared, reusable cards)

Principles [V regulatory research 3.4, 7.2 C04/C05; A design]:

- A card is a **shopping occasion, not a person**: label, explicit
  preference tags and consent flags are printed on the card. No name,
  photo, age, sex, family status, occupation or student status,
  education, title, income or any socio-economic proxy, health or diet,
  religion, origin, address or location history.
- Tags only from `tag_vocabulary` (FK); forbidden attributes cannot be
  stored. The agent-facing `MemberProfile` has no free-text field.
- Salutation (Sie/du) is an explicit card preference, never inferred.
- History is synthetic (8 weeks, seed 2027) and used only with
  `profiling = true`.
- Uniform shelf price: personas change only coupons, never a shelf or
  ESL price, and there are no "member prices" (a public member price is
  a public reduction under A11).

| Card (`membership_identification_value`) | Member | Persona label | Tags (explicit) | Consent offers / profiling | Anrede | Synthetic history (8 weeks) | Points |
|---|---|---|---|---|---|---|---|
| CLUB-0001 | M-0001 | **Kaffeepause** | kaffee, gebaeck, suesswaren | yes / yes | Sie | Espresso every 9 days, Cantuccini 2x | 1.240 |
| CLUB-0002 | M-0002 | **Filmabend** | snacks, dips, getraenke_alkoholfrei | yes / yes | du | Tortilla Chips weekly, Guacamole 1x | 380 |
| CLUB-0003 | M-0003 | **Badezeit** | drogerie, geschenke | yes / yes | Sie | Schaumbad monthly, GEBIT Ente 1x (5 weeks ago) | 655 |
| CLUB-0004 | M-0004 | **Nur Basis** | (none) | yes / **no** | Sie | none stored (points only) | 90 |
| CLUB-GAST (optional) | M-0099 | Gastkarte | (none) | no / no | Sie | none, `anonymous=true`, no `customer_id` | 0 |

Card format: Code 128 `CLUB-000n` printed on a laminated card; must
not start with the control prefix `##CTL:` (DESIGN 2.9). Pseudonymous
`customer_id` `CUST-DEMO-000n` only so that the GEBIT field
(`anonymous=false` requires a customer) is realistic.

Monitor "Grundlage" line per path (replaces DESIGN's single sentence,
which is no longer literally true with member cards):

- anonymous: "Grundlage: nur dieser Bon. Kein Profil gespeichert."
- member with profiling: "Grundlage: Kartenpraeferenzen und Einkaeufe
  der letzten 8 Wochen (fiktive Karte). Regalpreis fuer alle gleich."
- member without profiling: "Grundlage: nur dieser Bon. Karte ohne
  Profil-Einwilligung."

Booth notice: "Fiktive Kundenkarten ohne Personenbezug. Regalpreis fuer
alle gleich, persoenlich ist nur der Coupon." (UI renders umlauts.)

### 2.8 Flows between the POS simulator, the loyalty service and SAM

All GEBIT-side payloads below were validated against purchase-api
2.50.0 / receipt-api 2.13.0 (`examples/gebit_*.json`) [V].

**Card scan (TR5)**

1. Kasse button "Kundenkarte Kaffeepause" ->
   `AssignLoyaltyMembership{header{trace_id "v-0217-0042.card", originator{identity_id "ID199901"}}, purchase_transaction_id, membership_identification_value "CLUB-0001", capturing_information{SCAN, CODE128, "CLUB-0001"}}`.
2. `gpos-pos` -> `LoyaltyService.ResolveMembership` (gRPC, ms) ->
   `MembershipResolution{membership_id M-0001, program POINTS-ID/"POINTS", customer_id CUST-DEMO-0001, verified, ACTIVE, accounts[{POINTS-ACCOUNT-ID, balance 1240}], coupons[] (wallet), membership_preferences[showcase.personaLabel=Kaffeepause]}`.
3. `gpos-pos` writes `PurchaseTransaction.loyalty.loyalty_memberships[]`,
   then emits `LoyaltyMembershipAssigned{membershipPositionId, capturingInformation}`
   on `gebit/rp/purchase/v2/loyalty/LoyaltyMembershipAssigned/DE/999/101/01/{txId}`,
   plus one `LoyaltyCouponAssigned` per open wallet coupon
   (`from_membership=true`) [A: GEBIT behaviour, question L2].
   The loyalty service emits `MembershipResolved` (monitor: "Kundenkarte
   erkannt: Kaffeepause").
4. SAM rule R1 (all booth-till raw events) starts `gpos-pos-event`;
   `assess_event` gets the membership via `GetPurchaseTransaction`
   (the event has no membership id) and returns verdict `member`.

**Coupon issue and redemption (TR5)**

5. Tool nodes `get_member_profile` and `get_offers` (engine -> gRPC),
   agent `gpos-loyalty-agent` (fast) picks slot A or B and writes one
   sentence, tool node `issue_coupon` (`IssueCoupon`, channel AGENT)
   -> `CouponIssued`; the engine keeps the code and the BFF shows the QR
   on the customer display.
6. Host scans the QR -> `AssignLoyaltyCoupon{coupon_identification_value "LC-7Q2K-0042"}`
   -> `ResolveCoupon` (VALID or NOT_APPLICABLE) ->
   `LoyaltyCouponAssigned{membershipPositionId, couponPositionId}`.
   The pricing stub applies the discount when the target article is in
   the basket (`LoyaltyCoupon.applied=true`, position discount
   `RELATIVE 30.00`, `amount 0.69`, receipt `promotion_id
   promo-cantuccini-30`); basket-value coupons become a
   `PromotionPaymentPosition` with `trigger.loyalty_membership{...}`.

**Anonymous coupon (TR4, next-visit vouchers)**

7. QR `GPOS:GUAC30` -> `ApplyAnonymousCoupon{prefix "GPOS", promotion_code "GUAC30"}`
   -> `ResolveCoupon` -> `AnonymousCouponApplied{couponPositionId}`;
   the stub prices the tied offer only while chips are in the basket.

**Closing, cancel, void**

8. `StartPaymentProcess` / `CreateCashPayment` -> in `IN_CLOSING`
   `gpos-pos` calls `CalculatePurchaseResult` (earned 4 points for
   9,59 EUR; checkout coupon OFF-SCHAUMBAD-30 if an Ente was on the
   receipt) and writes `receipt.loyalty` (validated example
   `gebit_receipt_Loyalty_member.json`: membership with `accounts` map,
   coupon `applied=true`, `earnedAmounts`, `checkoutCoupons` with QR),
   then `ReportPurchase` (books points, marks coupons REDEEMED,
   creates checkout coupons) -> `PointsEarned`, `CouponRedeemed`,
   `CouponIssued(channel CHECKOUT)` -> `PurchaseTransactionClosed`.
9. `CancelPurchaseTransaction` -> nothing is reported: no points, no
   redemption, coupon stays ISSUED (C03).
10. `VoidPurchaseTransaction` (Bonstorno, deep corner) ->
    `ReportPurchase{transaction_type VOID, referenced_purchase_transaction_id}`
    -> `PointsReversed` (negative `earned_amount` on the VOID receipt,
    as the receipt proto demands).

### 2.9 SAM usage: MCP tools (engine facade) and where they run

Rules applied (sibling tracks, [V] there): tools return Pydantic models
(only then `mcp_structured_content.<field>` resolves), each result
below 2048 bytes, the MCP connector needs a manifest list, agent-level
tool approval is a fail-safe denial for event-mesh runs, the gated
workflow `tool` node needs `SAM_FEATURE_WORKFLOW_HIL_PAUSE_RESUME`
(HITL track 0.1-0.2), `ask_user_question` errors on event channels.
Each agent tool call costs a model round trip (fast agent 4.5-5.6 s
for one call), so reads run as **tool nodes before the agent**.

```python
# app/gposdemo/engine/tools_loyalty.py (signatures; registered on gpos-booth-tools)
class MemberProfileResult(BaseModel):
    member_ref: str                      # "M-0001"
    persona_label: str                   # "Kaffeepause"
    salutation: Literal["Sie", "du"]
    tags: list[str]                      # allowlisted only
    consent_offers: bool
    consent_profiling: bool
    history: list[str] = []              # "kaffee: 7x in 8 Wochen" (profiling only)
    points: int
    open_coupons: int

class OfferSlot(BaseModel):
    slot: Literal["A", "B", "C"]
    offer_id: str
    kind: Literal["PERSONAL_COUPON", "TIED_OFFER", "CHECKOUT_COUPON"]
    article: str
    price_before: float
    price_after: float
    pct: int
    valid_days: int
    why_facts: list[str]                 # every number the agent may cite
    blocked_rule: str = ""

class OffersResult(BaseModel):
    member_ref: str = ""
    personalised: bool
    recommended: str
    slots: list[OfferSlot]               # <= 3

class CouponResult(BaseModel):
    status: Literal["issued", "duplicate", "blocked", "no_consent", "invalid_text"]
    coupon_id: str = ""                  # never the code
    offer_id: str = ""
    blocked_rule: str = ""
    text_source: Literal["llm", "template"] = "template"

class RedeemResult(BaseModel):
    status: Literal["redeemed", "already_settled", "not_closed", "unknown"]
    coupons: int = 0
    points: int = 0

@mcp.tool()
def get_member_profile(member_ref: str, run_id: str) -> MemberProfileResult: ...
@mcp.tool()
def get_offers(tx_id: str, run_id: str, member_ref: str = "") -> OffersResult: ...
@mcp.tool()
def issue_coupon(tx_id: str, member_ref: str, offer_id: str, slot: str,
                 display_text: str, proposal_id: str, run_id: str) -> CouponResult: ...
@mcp.tool()
def redeem_coupon(tx_id: str, run_id: str) -> RedeemResult: ...
```

| Tool | Runs as | Gate | Why |
|---|---|---|---|
| `get_member_profile` | tool node (verdict `member`) | none | read-only, saves an agent turn |
| `get_offers` | tool node | none | deterministic ranking; agent picks only among unblocked slots |
| `issue_coupon` | tool node after the agent (agent output `{slot, text}`) | none (catalogue, caps enforced server side, text validated like DESIGN 8.4) | LLM never writes state (D01) |
| `redeem_coupon` | tool node in the `close` branch, **lab mode only** | none | in sim mode the POS already reported (returns `already_settled`); in the GEBIT lab GEBIT's purchase service does not call us, so we settle from the receipt. Never an agent tool |
| `apply_coupon_campaign` (TR2 slot B) / special coupons | `type: tool` node in the tool-only approval workflow | `hil.require_approval_when auto_ok` (HITL track 5.1) | needs a human; must not hang on an agent |

`notify_user` (group `notification_tools`, scope `notify:_:send`) as
tool nodes: "Kundenkarte Kaffeepause: Coupon Cantuccini -30 % (Regel)"
and every "Vorschlag wartet auf Freigabe".

### 2.10 Swap to the GEBIT lab

| Concern | Simulation | GEBIT lab |
|---|---|---|
| Card scan | our POS calls `ResolveMembership` | GEBIT's purchase service asks its own loyalty connector; our cards are probably `verified=false` unless GEBIT wires our service (L1). Engine reads `membership_identification_value` via `GetPurchaseTransaction` and resolves it read-only at our service |
| Member coupon discount | our pricing stub | needs a promotion in GEBIT's promotion engine per coupon type (L3) |
| Tied offer | stub prices `GPOS:GUAC30` | promotion with that prefix/code in GEBIT (L3) |
| Points, checkout coupons | `CalculatePurchaseResult` at closing | GEBIT's program (`POINTS-ID` already exists in their sample); our `redeem_coupon` settles our side from the closed receipt |
| Contract offered to GEBIT | - | our `LoyaltyService` proto as the "external loyalty system" adapter |

---

## 3. Price-change trigger catalogue

### 3.1 Shared rules (from DESIGN 8.1/8.2, kept; MHD parts removed)

- **Direction and uniformity**: reductions only (B01), one shelf price
  per article and store (B08/C01); personalisation only through coupons
  that reduce.
- **Price point** (shelf promotion and markdown): highest price ending
  ,99 ,89 ,79 or ,49 at or below the exact step price. Coupons and tied
  offers: exact percentage, floored to the cent.
- **PAngV for announced shelf reductions** (unchanged, not simplified):
  `ref30 = min(prices applied in the 30 days before the reduction)`;
  strike-through = `ref30`; shown % = `floor((ref30 - p) / ref30 x 100)`;
  if `p >= ref30` no reduction wording (A03); the line "Niedrigster Preis
  der letzten 30 Tage: X EUR" in the same block (A04, BGH I ZR 183/24);
  Grundpreis recomputed (A08); stepwise uninterrupted reductions keep the
  first `ref30` (section 11 (2), A06); a finished promotion inside the
  window becomes the new `ref30` (A07).
- **Not covered by the 30-day line** (still truthful, UWG): personal
  coupons = individual reductions (section 11 (4) no. 1; Commission
  notice 2.3); tied conditional offers (notice section 3, critic C4);
  bonus points (continuous loyalty programme, notice 2.3). No
  perishable exception any more (MHD dropped).
- **Booth reset vs `ref30`** (new): approved booth promotions are a
  per-visit overlay that the reset removes; they must not be written
  to the scenario's `price_history`, otherwise the next visitor's
  `ref30` is 6,89 and "-20 %" can no longer be shown (A07).
- **Guardrails**: margin floor net 20 % non-food / 12 % food (B04);
  one-click cap 30 % shown discount, above that "Zweitfreigabe"
  (blocked at the booth); max 2 changes per article and store day,
  cooldown 60 store minutes (B06); promotion collision blocks (G01);
  price-bound and excluded categories never (G02); **new G03 no
  stacking**: no coupon on an article with an active shelf promotion;
  stock must cover the forecast of an advertised promotion (A13).
- **Concurrency**: at most one open HITL proposal per till; a second
  trigger in the same visit shows only its insight chip until the first
  is decided [A].
- **Approval mechanics** (HITL track 5.1): proposals are staged with
  `auto_ok` from the policy; shelf-price changes have `auto_ok=false`
  and pause in the gated `apply_price` node of `gpos-price-approval`
  (run identity `marktleitung@solace.lab`, inbox via the notification
  service); fallback = signed tablet decision -> `gpos-apply-decision`.
  The native card is approve/deny only: slot B needs a second proposal
  or the tablet.

### 3.2 Overview

| ID | Trigger (Ausloeser) | GEBIT event | SAM path | Proposal type | Human approval | Demo article and numbers |
|---|---|---|---|---|---|---|
| TR1 | Ladenhueter gegen Plan | `PositionAdded{article004}` + closed receipts | `gpos-pos-event` -> agent `gpos-pricing-agent` (fast) -> `gpos-price-approval` | temporary promotion | yes | GEBIT Ente 8,67 -> 6,89 (-20 %) bis Fr 20:00, +8,7 EUR |
| TR2 | Ueberbestand nach Lieferavis | `PositionAdded{article030}` + delivery advice | same | promotion (A) or member coupon campaign (B) | yes | Kaffeepads 4,99 -> 3,99 (-20 %), +14,5 EUR; B: coupon -30 % for tag kaffee |
| TR3 | Wettbewerbspreis per Prospektfoto | none for the trigger (photo event); effect at next `PositionAdded{article007}` | `gpos-competitor-price` (multimodal) -> pricing agent -> approval | temporary promotion until the flyer ends | yes | Espresso 7,99 -> 6,99 (-12 %) bis Sa 20:00, +23,5 EUR |
| TR4 | Warenkorb-Affinitaet | `PositionAdded{article001}` (open basket) | `gpos-pos-event` -> tool `publish_offer` (no LLM) | tied offer | no (catalogue, "Regel") | Guacamole 2,09 statt 2,99 beim Kauf von Chips |
| TR5 | Mitgliedskarte | `LoyaltyMembershipAssigned` (+ basket) | `gpos-pos-event` -> loyalty tool nodes -> agent `gpos-loyalty-agent` (fast) -> `issue_coupon` | personalised loyalty coupon | no (catalogue); special coupon yes | Kaffeepause + Espresso: Cantuccini 1,60 statt 2,29 (-30 %) |
| TR6 | Saisonende | `PositionAdded{article017}` + season calendar | as TR1 | markdown (Abschrift bis Abverkauf), stepwise | yes | Valentins-Pralinen 6,99 -> 4,89 (-30 %), +34,9 EUR |
| TR7 | Leitplanke | `PositionAdded{article019 / article028}` | `assess_event` -> switch -> `note_event`, 0 LLM | none | n/a | Fruchtgummi (Aktion laeuft), Kochbuch (Preisbindung) |

Four of the six proposing triggers change the uniform shelf price.
Numbers are from `calc_triggers.py` (output `calc_output.txt`) [V
arithmetic; inputs A].

### 3.3 TR1 "Die Ente schwimmt nicht" (slow seller vs plan)

- **Condition** (unchanged from DESIGN S1): scan of `article004`;
  sell-through `5 / 14,7 = 0,34 < 0,60`, Poisson p 0,0034 < 0,05,
  planned so far >= 10; days of supply 4,1 vs target 2,0; no active
  promotion, not excluded, change budget and cooldown free. Sales count
  only from `PurchaseTransactionClosed` positions with `effectual=true`.
- **Data**: preset (stock 42, plan 30/day, v 0,85/h, elasticity -2,0,
  horizon 30 h until Fr 19.02. 20:00, leftover weight 0,4); store note
  "Lieferavis: Freitag nach Ladenschluss kommen 24 weitere Enten" (the
  agent reads it).
- **SAM**: rule R1 -> `gpos-pos-event` -> `assess_event` (verdict
  `propose_price`) -> agent `gpos-pricing-agent` (fast, slot + text)
  -> `stage_proposal` -> `notify_user` -> `gpos-price-approval` (gated
  `apply_price`).

| Step | Price | Shown | Units by Fr | Left | Gross profit | Delta | Margin | Result |
|---|---|---|---|---|---|---|---|---|
| none | 8,67 | - | 25,5 | 16,5 | 44,5 | 0 | 39,6 % | base |
| -10 % | 7,79 | -10 % | 31,6 | 10,4 | 49,5 | +4,9 | 32,8 % | slot B |
| **-20 %** | **6,89** | **-20 %** | 40,4 | 1,6 | 53,3 | **+8,7** | 24,0 % | **slot A** |
| -30 % | 5,99 | -30 % | 42,0 | 0 | 26,6 | -17,9 | 12,6 % | blocked: margin < 20 % |
| -40 % | 4,99 | -42 % | 42,0 | 0 | -8,7 | -53,2 | -4,9 % | blocked: margin, > 30 % |

- **PAngV**: `ref30` 8,67 (promo week 6 weeks ago is outside the
  window); "-20 %" (20,5 floored); 30-day line 8,67 EUR; piece goods,
  no Grundpreis.
- **Approval**: yes. Variants T2-T4 of DESIGN (ref30 trap, context
  beats calculation, prompt injection) stay valid on this trigger.

### 3.4 TR2 "Zu viel Kaffee im Anmarsch" (overstock + delivery advice)

- **Condition**: scan of `article030`; the article sells **on plan**
  (sell-through 0,97), but a delivery advice is open: 72 pads arrive
  Do 18.02. 07:00 (ordered 24, supplier sends a promo display).
  Projected stock at the horizon end (Fr 20:00, 30 h) =
  40 + 72 - 42 = 70 against a target of 34 (2 days at plan 16,8/day):
  excess 36 > 10 % of available stock. Same budget/collision checks as
  TR1.
- **GEBIT events + data**: `PositionAdded`. The delivery advice is not
  a Purchase API concept (no goods receipt in the API [V]); it comes
  from the scenario preset or an operator control
  (`gpos/v1/control/inbound`), stored in `inbound_delivery`, and its
  free text goes to the agent.
- **SAM**: as TR1; the agent may pick slot B only with a cited reason.
- **Numbers** (price 4,99, 7 % VAT, net cost 2,45, v 1,4/h, elasticity
  -2,2 because coffee is a classic promotion category in Germany [A],
  excess weight 0,3):

| Step | Price | Shown | Units | Excess | Gross profit | Delta | Margin | Result |
|---|---|---|---|---|---|---|---|---|
| none | 4,99 | - | 42,0 | 36,0 | 66,5 | 0 | 47,5 % | base |
| -10 % | 4,49 | -10 % | 53,0 | 25,0 | 74,1 | +7,6 | 41,6 % | |
| **-20 %** | **3,99** | **-20 %** | 68,7 | 9,3 | 81,0 | **+14,5** | 34,3 % | **slot A** |
| -30 % | 3,49 | -30 % | 92,2 | 0 | 74,9 | +8,3 | 24,9 % | allowed, lower |
| -40 % | 2,99 | -40 % | 112,0 | 0 | 38,6 | -27,9 | 12,3 % | blocked: > 30 % |

- **Slot B (loyalty)**: "Mitglieder-Coupon -30 % (3,49 EUR) fuer
  Karten mit Tag kaffee, bis Fr" = activation of OFF-KAFFEEPADS-30 for
  that segment. Shelf price stays 4,99; individual reduction, not
  advertised publicly. Needs approval as a campaign (gated
  `apply_coupon_campaign`); single coupons then go out by rule (TR5
  ranks Kaffeepads with a clearance bonus).
- **PAngV**: `ref30` 4,99; "-20 %" exact (3,99 = 20,04 %); Grundpreis
  36 x 7 g = 252 g: 3,99 EUR -> 15,83 EUR/kg (regular 19,80 EUR/kg).
- **Approval**: yes (A and B).

### 3.5 TR3 "Die Konkurrenz wirbt mit 6,99" (competitor flyer photo, multimodal)

- **Condition**: a photographed flyer of a fictional competitor
  ("Wettbewerber Nord (fiktiv)", laminated prop; never a real chain,
  never the competitor's name on customer-facing screens) shows
  "Espresso Bohnen 500 g 6,99 EUR, gueltig 15.-20.02.". Extraction is
  readable, matches our `article007` (same pack size, fuzzy name match),
  price within the plausibility band; Espresso is a KVI with the policy
  "never above a competitor promotion, never undercut" [A]; our observed
  velocity since Monday 0,9/h vs plan 1,5/h supports it.
- **Events**: no GEBIT event triggers it (GEBIT has no competitor-price
  API [V]); the photo event (`gpos/v1/vision/competitor-photo/...`,
  multimodal track 2.1) starts it, the effect is visible at the next
  `PositionAdded{article007}`. Stated honestly on the monitor.
- **SAM**: rule R2 with `artifactProcessing` -> `gpos-competitor-price`:
  `describe_image` tool node (Haiku) or agent with `load_artifact`
  (fallback) -> `match_competitor_price` -> switch -> pricing agent ->
  approval. Transport and `describe_image` config are [G0] in the
  multimodal track (S1-S3). The approver sees photo and extracted
  values side by side on our monitor (the SAM card is text only).
- **Numbers** (price elasticity relative to the competitor calibrated
  from the observed drop, -3,82; horizon 42 h until Sa 20:00; stock 72
  covers 63 expected units, A13):

| Option | Price | Shown | v/h | Units | Gross profit | Delta | Margin |
|---|---|---|---|---|---|---|---|
| none | 7,99 | - | 0,90 | 37,8 | 123,5 | 0 | 43,8 % |
| halve the gap | 7,49 | -6 % | 1,15 | 48,4 | 135,5 | +12,0 | 40,0 % |
| **match** | **6,99** | **-12 %** | 1,50 | 63,0 | 147,0 | **+23,5** | 35,7 % |

- **Proposal**: temporary promotion until Sa 20.02. 20:00 (the end of
  the competitor promotion). Not a permanent markdown and not a silent
  temporary cut: raising the price later would be an intraday increase
  (B07); only the scheduled end of an announced promotion is allowed.
- **PAngV**: `ref30` 7,99; "-12 %" (12,5 floored); 30-day line;
  Grundpreis 13,98 EUR/kg (regular 15,98); no comparative claim
  ("guenstiger als ...") and no competitor name on label or customer
  display (UWG section 6 risk avoided).
- **Approval**: yes. Variant TR3b: the flyer also shows the cookbook ->
  G02, no reaction (combines with TR7).
- Note: the multimodal track's prop example uses the Ente; we recommend
  a different article so the triggers stay distinct.

### 3.6 TR4 "Chips ohne Dip?" (basket affinity, tied offer)

- **Condition**: `PositionAdded{article001}` in the open basket; rule
  Chips -> Guacamole lift 2,6, confidence 0,18 (inside 0,10-0,40; the
  Salsa rule at 0,42 stays blocked as cannibalisation); Guacamole not
  in the basket and in stock; catalogue offer active; one live offer
  per transaction; offer expires at `PaymentProcessStarted`.
- **SAM**: `gpos-pos-event` -> verdict `tied_offer` -> tool node
  `publish_offer` (template text, 0 LLM calls). With a member card the
  text can take the card's salutation (no extra call).
- **Offer**: "Guacamole 200 g fuer 2,09 EUR beim Kauf von Tortilla
  Chips · Einzelpreis 2,99 EUR · 1 kg = 10,45 EUR". Margin 30,9 %;
  expected gross profit per display 0,21 EUR (P_accept 0,35).
- **Redemption**: host scans `GPOS:GUAC30` -> `ApplyAnonymousCoupon`
  -> `AnonymousCouponApplied` -> 0,90 EUR off the Guacamole line.
- **Legal**: tied conditional offer, outside Art. 6a; conditions and
  Grundpreis shown; shelf price unchanged.
- **Approval**: no (pre-approved catalogue, labelled "Regel").

### 3.7 TR5 "Ihre Karte, Ihr Coupon" (loyalty member, personalised coupon)

- **Condition**: `LoyaltyMembershipAssigned` with a verified member,
  `consent.offers=true`; candidates from `ListEligibleOffers`
  (preference match x affinity x expected margin + clearance bonus);
  frequency (one open coupon per member and offer), no stacking (G03).
- **Numbers** for CLUB-0001 "Kaffeepause" with Espresso in the basket:

| Slot | Offer | Price | Discount | Margin | Score | Note |
|---|---|---|---|---|---|---|
| **A** | Cantuccini -30 % | 2,29 -> **1,60** | 0,69 | 36,5 % | 0,121 | affinity Espresso -> Cantuccini lift 2,9 |
| B | Kaffeepads -30 % | 4,99 -> 3,49 | 1,50 | 24,9 % | 0,104 | clearance bonus from TR2; within 20 % of A, agent may pick it with a cited reason |

- Basket Espresso 7,99 + Cantuccini 1,60 = 9,59 EUR -> 4 points
  (balance 1.240 -> 1.244).
- **Variants**: CLUB-0004 "Nur Basis" -> same offers from this basket
  only, `history_used=false`, monitor line "Karte ohne
  Profil-Einwilligung"; CLUB-GAST -> no personal coupon, only TR4 or a
  welcome checkout coupon; Ente on the receipt -> checkout coupon
  OFF-SCHAUMBAD-30 for the next visit (2,95 -> 2,06).
- **Legal**: individual reduction, no 30-day line; label "Ihr
  persoenliches Mitglieder-Angebot"; shelf price unchanged.
- **Approval**: no for catalogue coupons; a special coupon (e.g. -40 %)
  goes to the gated approval workflow.

### 3.8 TR6 "Nach dem Valentinstag" (season end)

- **Condition**: `PositionAdded{article017}`; season end 14.02.2027
  (a Sunday) is before the store date Mi 17.02.2027 [V calendar];
  post-season velocity 0,36/h (0,3 x 1,2); projected leftover at the
  horizon (Di 23.02. 20:00, 66 store hours, Sunday closed) 36 of 60.
- **Numbers** (6,99, 7 %, net cost 3,20, elasticity -2,0, leftover
  weight 0,6):

| Step | Price | Shown | Units | Left | Gross profit | Delta | Margin | Result |
|---|---|---|---|---|---|---|---|---|
| none | 6,99 | - | 23,8 | 36,2 | 9,6 | 0 | 51,0 % | base |
| -10 % | 5,99 | -14 % | 32,4 | 27,6 | 24,5 | +14,9 | 42,8 % | |
| -20 % | 5,49 | -21 % | 38,5 | 21,5 | 33,1 | +23,5 | 37,6 % | slot B |
| **-30 %** | **4,89** | **-30 %** | 48,5 | 11,5 | 44,5 | **+34,9** | 30,0 % | **slot A** |
| -40 % | 3,99 | -42 % | 60,0 | 0 | 31,7 | +22,1 | 14,2 % | blocked: > 30 % |

- **Proposal**: markdown (article master price, "Saisonware reduziert",
  until sold out; no later increase, B07). Stepwise plan: a second step
  -42 % on Saturday would need the second approval; as an uninterrupted
  stepwise reduction it may keep `ref30` 6,99 (section 11 (2), A06).
- **PAngV**: not perishable, so no section 11 (4) no. 2 exception
  (critic C5); `ref30` 6,99; "-30 %" (30,04 floored); Grundpreis 200 g:
  24,45 EUR/kg (regular 34,95).
- **Approval**: yes.

### 3.9 TR7 "Hier macht der Agent nichts" (guardrails, no proposal)

- **TR7a promotion collision**: `PositionAdded{article019}` Fruchtgummi
  with a running promotion -15 % until So 21.02. -> G01; coupons on it
  blocked too (G03). Chip "Aktion laeuft bereits - kein Vorschlag".
- **TR7b price binding**: `PositionAdded{article028}` Kochbuch
  "Rheinische Kueche" -> G02 (BuchPrG): no promotion, no coupon, and no
  bonus points (`points_eligible=false`; conservative choice [A]).
- **SAM**: verdict `excluded` / `collision` -> `note_event`; agent node
  greyed out in Activities; 0 LLM calls; optional `notify_user`
  "Leitplanke gegriffen".
- **Approval**: n/a.

### 3.10 How the POS simulator raises each trigger

| Kasse / operator action | GEBIT command (or own event) | Resulting events | Trigger |
|---|---|---|---|
| Artikel "GEBIT Ente" | `AddArticle{article_id IDarticle004, capturing SCAN/EAN13}` | (`PurchaseTransactionOpened` on first scan) `PositionAdded` | TR1 |
| Artikel "Kaffeepads" | `AddArticle{IDarticle030}` | `PositionAdded` | TR2 |
| /op "Lieferavis +72 Kaffeepads" | own `gpos/v1/control/inbound` | - | TR2 data |
| Tablet "Prospektfoto" | own `gpos/v1/vision/competitor-photo/...` | - | TR3 start |
| Artikel "Espresso" | `AddArticle{IDarticle007}` | `PositionAdded` (shows 6,99 after approval) | TR3 effect, TR5 basket |
| Artikel "Tortilla Chips" | `AddArticle{IDarticle001}` | `PositionAdded` | TR4 |
| Coupon-QR `GPOS:...` | `ApplyAnonymousCoupon{prefix, promotion_code}` | `AnonymousCouponApplied` | TR4 redemption, next-visit voucher |
| Kundenkarte `CLUB-000n` | `AssignLoyaltyMembership` | `LoyaltyMembershipAssigned` (+ `LoyaltyCouponAssigned` per wallet coupon) | TR5 |
| Coupon-QR `LC-...` | `AssignLoyaltyCoupon` | `LoyaltyCouponAssigned` or `UnverifiedLoyaltyCouponAssigned` | TR5 redemption |
| Artikel "Valentins-Pralinen" | `AddArticle{IDarticle017}` | `PositionAdded` | TR6 |
| Artikel "Fruchtgummi" / "Kochbuch" | `AddArticle{IDarticle019 / IDarticle028}` | `PositionAdded` | TR7 |
| Summe, Bar | `StartPaymentProcess`, `CreateCashPayment` | ... `PurchaseTransactionClosed` (receipt incl. loyalty) | points, redemption, checkout coupon |
| Bon abbrechen | `CancelPurchaseTransaction` | `InCancellation`, `Cancelled` | nothing booked |
| Bonstorno (deep corner) | `VoidPurchaseTransaction` | VOID transaction closed | `PointsReversed` |
| /op "Einwilligung aus" | `ChangeConsent` (loyalty gRPC) | `ConsentChanged` | TR5 variant |

`AddArticle` takes the technical `article_id`, not the EAN [V purchase
research 3.2]. Background tills never reach SAM (DESIGN 3.5).

Suggested booth use [A]: Express = TR1; guided = TR1 + TR5 (card) +
TR4 or TR7; deep corner = TR3 (photo) and the ref30 trap. TR2 and TR6
are alternative heroes per fair day or per visitor type (grocery vs
non-food), selectable by control card.

---

## 4. Changes needed in DESIGN.md (for the integration step)

1. 3.2 S2 "MHD-Retter" and all MHD parts (7.2 `article010M`, 8.2
   `perishable_mhd`, 8.5 point 4, A05 references) removed; 3.x becomes
   the TR1-TR7 catalogue.
2. 3.6 "Personas und Kundenkarten" moves from the reserve into v1;
   7.7 replaced by section 2.7 here; the "Grundlage" sentence becomes
   path-dependent; T5 (Kombi-Angebot) becomes TR4 in v1.
3. 4.2 components: fourth deployment `gpos-loyalty` (gRPC :50052),
   schema `loyalty`; DESIGN's `voucher` table and `voucher_template`
   move into `loyalty.coupon` / `loyalty.offer` (one source of truth).
4. 5.4 topics: add `showcase/loyalty/v1/...` (ACL for the BFF) and the
   competitor photo topic; rule R2 on the entrypoint.
5. 6.6 tools: add the loyalty tools (2.9), `publish_offer`,
   `match_competitor_price`; `issue_voucher` becomes a call to
   `IssueCoupon`/`CalculatePurchaseResult`.
6. 7.2 assortment: add article030 Kaffeepads 36 St (7 %, 4,99, net cost
   2,45, 252 g), article017 Pralinen, article001/003 from the reserve;
   Espresso becomes the TR3 article.
7. 8.2 policy: add `overstock` (target days 2, excess > 10 %),
   `competitor` (KVI list, match never undercut, plausibility band,
   min extraction confidence), `season_end` (dates, stepwise),
   `coupons` (catalogue caps 30 % / 3 EUR, G03 no stacking, frequency),
   `tied_offers`; keep `one_proposal_per_visit` as "one open HITL
   proposal per till".
8. 8.1: note that booth-applied promotions never enter `price_history`.
9. 7.1 engine schema: add `inbound_delivery` (TR2 delivery advice:
   article, quantity, expected_at, free text) and
   `competitor_observation` (TR3: photo ref, extracted values,
   confidence, matched article, valid_to); 7.6 presets per trigger.

---

## 5. Open questions, risks, spikes

Questions for GEBIT (loyalty-specific, to add to DESIGN 14.3):

- L1. Which loyalty system does the purchase service call on
  `AssignLoyaltyMembership`, and can an external system be plugged in
  (interface, transport, contract)? Would they accept our proto?
- L2. Are coupons that come with a membership emitted as
  `LoyaltyCouponAssigned{from_membership}` automatically?
- L3. How does a loyalty coupon or an anonymous coupon become a price
  action: one promotion per coupon type in the promotion engine? API to
  create them in the lab? Semantics of `prefix` (e.g. GS1 98/99)?
- L4. Earn rule behind `POINTS-ID` (4 points for 8,67 EUR), and is a
  loyalty simulator running in their lab?
- L5. Is `deferred_purchase_report_request` used; which message type?
- L6. Can an external loyalty response produce a `CheckoutCoupon` at
  closing?

Risks:

- Native workflow HITL needs a feature flag that is off in the lab
  (HITL track); until G0-19 passes, the tablet fallback is the booth
  path for TR1/TR2/TR3/TR6.
- Image transport into a workflow (`artifactProcessing`) and
  `describe_image` configuration are unproven (multimodal track S1-S3);
  TR3 has preset fallbacks there.
- Shared persona cards: without the per-visit reset the wallet fills up
  and the frequency rule blocks the next visitor.
- Bearer coupon codes must stay off the broker and out of agent
  context; a test should assert that no event payload matches the code
  pattern.
- LLM cost: TR5 adds one fast call per card scan, TR3 one vision call
  plus one fast call; keep the budget breaker of DESIGN 8.2.
- The DDL was syntax-checked only; run it once against Postgres 18 in
  the first build step (no lab writes were allowed here).
- Effort estimate for the loyalty service [A]: about 8 person days
  (proto and server scaffold 1,5; schema, seed and history generator 1;
  POS integration for resolve, coupons and closing 2; engine MCP tools
  1,5; outbox and events 0,5; tests 1; cards and props 0,5).

---

## 6. Verification log

| Check | Command / file | Result |
|---|---|---|
| Loyalty messages and services in GEBIT descriptor sets | `IMPL/loyalty-tools/fds_scan.py` on `purchase-api-2.50.0.pb`, `receipt-api-2.13.0.pb` | 1 service (106 RPCs), loyalty only as commands/events/datatypes [V] |
| No loyalty service in the GEBIT HTML docs | grep on `SP/tools/purchase_html.txt`, `receipt_html.txt` | "LoyaltyService/LoyaltySystem" 0 hits [V] |
| Our proto compiles | `protoc 34.1 --include_imports --descriptor_set_out` over 11 files | OK, 23,811-byte `.pb` [V] |
| Example payloads | `validate_examples.py` (strict `ParseDict`, unknown fields rejected) | 14/14 OK; largest `EligibleOffers` 1,591 B compact (< 2048) [V] |
| DDL and seed syntax | pglast 8.7 `parse_sql` | 22 + 10 statements parsed [V syntax only] |
| Trigger numbers | `calc_triggers.py` | TR1 equals DESIGN S1; TR2-TR6 as tables above [V arithmetic] |
| Calendar | Python `date.strftime` | 14.02.2027 Sunday, 17.02.2027 Wednesday, 23.02.2027 Tuesday [V] |
