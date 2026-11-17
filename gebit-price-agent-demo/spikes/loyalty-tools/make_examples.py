"""Write example JSON payloads (ours and GEBIT-shaped) for the loyalty track."""
import json, os, sys, datetime as dt
out = sys.argv[1]
CET = dt.timezone(dt.timedelta(hours=1))
def ts(h, m, s, day=17, nanos=0, offset=None):
    t = dt.datetime(2027, 2, day, h, m, s, tzinfo=CET)
    d = {"seconds": str(int(t.timestamp()))}
    if nanos: d["nanos"] = nanos
    if offset is not None: d["offset"] = offset
    return d
TX = "5b1f0c2e-8d4a-4f6b-9a1e-2c7d3e4f5a60"
MPOS = "0e4d2b9c-1a2b-4c3d-8e9f-a0b1c2d3e4f5"
CPOS = "7c1f6a20-55e1-4d0b-9a3c-2b8e4f1d6a77"
ACPOS = "a1b2c3d4-0000-4e5f-8a9b-1c2d3e4f5a99"
def eur(cents, scale=2): 
    return {"currency": "EUR", "amount": {"scale": scale, "intVal": str(cents)}} if cents else {"currency": "EUR", "amount": {"scale": scale}}
ex = {}
# ---- GEBIT side (validated against purchase-api 2.50.0 / receipt-api 2.13.0) ----
ex["gebit_cmd_AssignLoyaltyMembership"] = ("de.gebit.rp.purchase.purchase.v2.command.AssignLoyaltyMembership", {
  "header": {"traceId": "v-0217-0042.card", "originator": {"identityId": "ID199901"}},
  "purchaseTransactionId": TX,
  "membershipIdentificationValue": "CLUB-0001",
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "CODE128", "inputValue": "CLUB-0001"}})
ex["gebit_evt_LoyaltyMembershipAssigned"] = ("de.gebit.rp.purchase.purchase.v2.event.LoyaltyMembershipAssigned", {
  "header": {"eventTimestamp": ts(14, 31, 52, nanos=410000000)},
  "metadata": {"offset": "5", "creationTimestamp": ts(14, 31, 52, nanos=395000000), "traceId": "v-0217-0042.card"},
  "purchaseTransactionId": TX,
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
  "membershipPositionId": MPOS,
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "CODE128", "inputValue": "CLUB-0001"}})
ex["gebit_cmd_AssignLoyaltyCoupon"] = ("de.gebit.rp.purchase.purchase.v2.command.AssignLoyaltyCoupon", {
  "header": {"traceId": "v-0217-0042.coupon", "originator": {"identityId": "ID199901"}},
  "purchaseTransactionId": TX,
  "couponIdentificationValue": "LC-7Q2K-0042",
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "QR", "inputValue": "LC-7Q2K-0042"}})
ex["gebit_evt_LoyaltyCouponAssigned"] = ("de.gebit.rp.purchase.purchase.v2.event.LoyaltyCouponAssigned", {
  "header": {"eventTimestamp": ts(14, 32, 30, nanos=212000000)},
  "metadata": {"offset": "8", "creationTimestamp": ts(14, 32, 30, nanos=201000000), "traceId": "v-0217-0042.coupon"},
  "purchaseTransactionId": TX,
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
  "membershipPositionId": MPOS,
  "couponPositionId": CPOS})
ex["gebit_cmd_ApplyAnonymousCoupon"] = ("de.gebit.rp.purchase.purchase.v2.command.ApplyAnonymousCoupon", {
  "header": {"traceId": "v-0217-0051.offer", "originator": {"identityId": "ID199901"}},
  "purchaseTransactionId": TX,
  "prefix": "GPOS", "promotionCode": "GUAC30",
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "QR", "inputValue": "GPOS:GUAC30"}})
ex["gebit_evt_AnonymousCouponApplied"] = ("de.gebit.rp.purchase.purchase.v2.event.AnonymousCouponApplied", {
  "header": {"eventTimestamp": ts(14, 40, 3, nanos=88000000)},
  "metadata": {"offset": "6", "creationTimestamp": ts(14, 40, 3, nanos=71000000), "traceId": "v-0217-0051.offer"},
  "purchaseTransactionId": TX,
  "prefix": "GPOS", "promotionCode": "GUAC30",
  "purchaseTransactionStatus": "PURCHASE_TRANSACTION_STATUS_OPEN",
  "couponPositionId": ACPOS,
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "QR", "inputValue": "GPOS:GUAC30"}})
ex["gebit_receipt_Loyalty_member"] = ("de.gebit.rp.receipt.receipt.v2.datatype.Loyalty", {
  "loyaltyMemberships": [{
    "membershipPositionId": MPOS, "membershipIdentificationValue": "CLUB-0001",
    "membershipId": "M-0001", "programId": "POINTS-ID", "programName": "POINTS",
    "customerId": "CUST-DEMO-0001", "anonymous": False, "voided": False, "verified": True,
    "coupons": [{"couponPositionId": CPOS, "couponIdentificationValue": "LC-7Q2K-0042",
                 "couponId": "CPN-0217-0042", "couponDescription": "Mitglieder-Coupon Cantuccini -30 %",
                 "fromMembership": False, "applied": True, "voided": False}],
    "accounts": {"POINTS-ACCOUNT-ID": {"accountId": "ACC-M-0001-POINTS", "accountType": "POINTS-ACCOUNT-ID",
                 "accountCurrency": {"id": "POINTS-CURRENCY-ID", "name": "Points"},
                 "accountBalanceBeforePurchase": {"value": "1240"}}},
    "membershipPreferences": [{"key": "showcase.personaLabel", "typedValue": {"stringValue": "Kaffeepause"}}]}],
  "loyaltyPurchaseResult": {
    "earnedAmounts": [{"application": {"program": {"id": "POINTS-ID", "name": "POINTS"},
                        "membershipId": "M-0001", "promotionId": "promotion-base-points", "reported": True},
                       "account": {"id": "POINTS-ACCOUNT-ID", "name": "points"},
                       "currency": {"id": "POINTS-CURRENCY-ID", "name": "Points"},
                       "earnedAmount": {"value": "4"},
                       "positionFractions": [{"positionId": "c0a8017e-3b2d-4e5f-8a9b-1c2d3e4f5a6b", "itemCount": 1, "fractionAmount": {"value": "4"}}]}],
    "checkoutCoupons": [{"application": {"program": {"id": "POINTS-ID", "name": "POINTS"},
                          "membershipId": "M-0001", "benefitId": "OFF-SCHAUMBAD-30",
                          "promotionId": "promo-schaumbad-30", "reported": True,
                          "extensionProperties": [{"key": "showcase.offerId", "typedValue": {"stringValue": "OFF-SCHAUMBAD-30"}}]},
                         "couponId": "CPN-0217-0044",
                         "printContent": {"lines": [
                           {"alignment": "ALIGNMENT_CENTER", "text": {"textElements": [{"plainText": "-30 % auf Schaumbad Lavendel, 14 Tage", "fontStyles": ["FONT_STYLE_BOLD"]}]}},
                           {"alignment": "ALIGNMENT_CENTER", "barcode": {"symbology": "SYMBOLOGY_QRCODE", "data": "LC-3M8P-0044", "textPosition": "TEXT_POSITION_BELOW"}}]}}]}})
# ---- our loyalty service (validated against showcase-loyalty-v1.pb) ----
ex["ours_qry_ResolveMembership"] = ("de.showcase.loyalty.v1.query.ResolveMembership", {
  "traceId": "v-0217-0042.card", "membershipIdentificationValue": "CLUB-0001",
  "purchaseTransactionId": TX, "location": "Root.DE.999.101.01",
  "capturingInformation": {"inputMethod": "SCAN", "inputType": "CODE128", "inputValue": "CLUB-0001"}})
ex["ours_dt_MembershipResolution"] = ("de.showcase.loyalty.v1.datatype.MembershipResolution", {
  "membershipIdentificationValue": "CLUB-0001", "membershipId": "M-0001",
  "programId": "POINTS-ID", "programName": "POINTS", "customerId": "CUST-DEMO-0001",
  "anonymous": False, "verified": True, "status": "MEMBERSHIP_STATUS_ACTIVE",
  "coupons": [],
  "accounts": [{"accountId": "ACC-M-0001-POINTS", "accountType": "POINTS-ACCOUNT-ID",
                "accountCurrencyName": "Points", "accountBalance": {"scale": 0, "intVal": "1240"}}],
  "membershipPreferences": [{"key": "showcase.personaLabel", "typedValue": {"stringValue": "Kaffeepause"}}],
  "receiptTextLines": ["Markt-Bonus: 1240 Punkte"]})
ex["ours_dt_EligibleOffers"] = ("de.showcase.loyalty.v1.datatype.EligibleOffers", {
  "recommendedSlot": "A", "personalised": True,
  "candidates": [
    {"slot": "A", "offer": {"offerId": "OFF-CANTUCCINI-30", "kind": "OFFER_KIND_PERSONAL_COUPON",
       "targetArticleNumber": "article008", "conditionArticleNumber": "article007",
       "discountType": "DISCOUNT_TYPE_RELATIVE", "discountValue": {"scale": 2, "intVal": "3000"},
       "maxDiscount": eur(100), "validDays": 7, "inCatalogue": True, "approval": "APPROVAL_MODE_NONE",
       "promotionId": "promo-cantuccini-30", "textKey": "coupon.cantuccini30", "matchTags": ["gebaeck", "kaffee"]},
     "score": {"scale": 3, "intVal": "121"}, "priceBefore": eur(229), "priceAfter": eur(160), "pctShown": 30,
     "whyFacts": ["Espresso im Korb", "Affinitaet Espresso -> Cantuccini Lift 2,9", "Tag gebaeck"]},
    {"slot": "B", "offer": {"offerId": "OFF-KAFFEEPADS-30", "kind": "OFFER_KIND_PERSONAL_COUPON",
       "targetArticleNumber": "article030", "discountType": "DISCOUNT_TYPE_RELATIVE",
       "discountValue": {"scale": 2, "intVal": "3000"}, "maxDiscount": eur(200), "validDays": 7,
       "inCatalogue": True, "approval": "APPROVAL_MODE_NONE", "promotionId": "promo-kaffeepads-30",
       "textKey": "coupon.kaffeepads30", "matchTags": ["kaffee"]},
     "score": {"scale": 3, "intVal": "104"}, "priceBefore": eur(499), "priceAfter": eur(349), "pctShown": 30,
     "whyFacts": ["Tag kaffee", "Ueberbestand nach Lieferavis: 36 ueber Zielbestand"]}]})
ex["ours_cmd_IssueCoupon"] = ("de.showcase.loyalty.v1.command.IssueCoupon", {
  "header": {"traceId": "v-0217-0042", "originator": {"identityId": "gpos-engine"}},
  "membershipId": "M-0001", "offerId": "OFF-CANTUCCINI-30", "channel": "ISSUE_CHANNEL_AGENT",
  "purchaseTransactionId": TX, "proposalId": "prp-0217-0043",
  "displayText": "Passt zu Ihrem Espresso: Cantuccini heute 1,60 EUR statt 2,29 EUR",
  "extensionProperties": [{"key": "showcase.samRunId", "typedValue": {"stringValue": "wfr-3f9a"}}]})
ex["ours_evt_CouponIssued"] = ("de.showcase.loyalty.v1.event.CouponIssued", {
  "header": {"eventTimestamp": ts(14, 32, 11, nanos=140000000)},
  "metadata": {"offset": "7", "creationTimestamp": ts(14, 32, 11, nanos=118000000), "traceId": "v-0217-0042"},
  "couponId": "CPN-0217-0042", "membershipId": "M-0001", "offerId": "OFF-CANTUCCINI-30",
  "kind": "OFFER_KIND_PERSONAL_COUPON", "channel": "ISSUE_CHANNEL_AGENT",
  "validTo": ts(20, 0, 0, day=24, offset=60),
  "discountType": "DISCOUNT_TYPE_RELATIVE", "discountValue": {"scale": 2, "intVal": "3000"},
  "targetArticleNumber": "article008", "purchaseTransactionId": TX, "proposalId": "prp-0217-0043",
  "extensionProperties": [{"key": "showcase.samRunId", "typedValue": {"stringValue": "wfr-3f9a"}}]})
ex["ours_evt_CouponRedeemed"] = ("de.showcase.loyalty.v1.event.CouponRedeemed", {
  "header": {"eventTimestamp": ts(14, 33, 40, nanos=505000000)},
  "metadata": {"offset": "8", "creationTimestamp": ts(14, 33, 40, nanos=490000000), "traceId": "v-0217-0042.close"},
  "couponId": "CPN-0217-0042", "membershipId": "M-0001", "purchaseTransactionId": TX,
  "couponPositionId": CPOS, "discountGranted": eur(69)})
ex["ours_evt_PointsEarned"] = ("de.showcase.loyalty.v1.event.PointsEarned", {
  "header": {"eventTimestamp": ts(14, 33, 40, nanos=507000000)},
  "metadata": {"offset": "9", "creationTimestamp": ts(14, 33, 40, nanos=491000000), "traceId": "v-0217-0042.close"},
  "membershipId": "M-0001", "accountId": "ACC-M-0001-POINTS",
  "amount": {"scale": 0, "intVal": "4"}, "balanceAfter": {"scale": 0, "intVal": "1244"},
  "purchaseTransactionId": TX, "promotionId": "promotion-base-points"})
os.makedirs(out, exist_ok=True)
for k, (t, d) in ex.items():
    body = {"@type": "type.googleapis.com/" + t}
    body.update(d)
    with open(os.path.join(out, k + ".json"), "w") as f:
        json.dump(body, f, indent=1, ensure_ascii=True)
print(len(ex), "examples written")
