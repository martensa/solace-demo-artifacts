-- Showcase Loyalty Service: schema "loyalty" in DB gpos.
-- Owned by role gpos_loyalty; the engine has no SQL grant here (it uses gRPC).
-- Portable to PostgreSQL 14+ (lab host: postgres:latest = 18; AKS: Azure
-- Database for PostgreSQL Flexible Server). No extension required.

create schema if not exists loyalty;
set search_path = loyalty;

-- Program, as in GEBIT's sample receipt (POINTS-ID / POINTS-ACCOUNT-ID).
create table program (
  program_id        text primary key,            -- 'POINTS-ID'
  program_name      text not null,               -- 'POINTS'
  display_name      text not null,               -- 'Markt-Bonus'
  account_type      text not null,               -- 'POINTS-ACCOUNT-ID'
  currency_id       text not null,               -- 'POINTS-CURRENCY-ID'
  currency_name     text not null,               -- 'Points'
  base_promotion_id text not null,               -- 'promotion-base-points'
  earn_eur_per_point numeric(6,2) not null check (earn_eur_per_point > 0)  -- 2.00
);

-- Article reference (category + loyalty eligibility), seeded from data/assortment.yaml.
create table article_ref (
  article_number   text primary key,             -- 'article008'
  article_id       text not null unique,         -- 'IDarticle008'
  name             text not null,
  category         text not null,                -- tag, e.g. 'gebaeck'
  points_eligible  boolean not null default true,-- false: price_bound, deposit
  coupon_eligible  boolean not null default true
);

-- Allowlist of preference tags (guardrail C04). Only allowed tags exist here,
-- so a forbidden attribute cannot be stored as a tag at all.
create table tag_vocabulary (
  tag      text primary key check (tag ~ '^[a-z_]{3,32}$'),
  label_de text not null
);

create table member (
  member_id     text primary key,                -- 'M-0001' = LoyaltyMembership.membership_id
  program_id    text not null references program,
  customer_ref  text unique,                     -- 'CUST-DEMO-0001'; null = anonymous
  persona_key   text not null unique,            -- 'kaffeepause'
  persona_label text not null,                   -- 'Kaffeepause'
  anonymous     boolean not null default false,
  salutation    text not null default 'FORMAL' check (salutation in ('FORMAL','INFORMAL')),
  status        text not null default 'ACTIVE' check (status in ('ACTIVE','BLOCKED')),
  is_fictional  boolean not null default true check (is_fictional),  -- never a real person
  created_at    timestamptz not null default now(),
  check (anonymous = (customer_ref is null))
);

create table card (
  card_value text primary key,                   -- membership_identification_value
  member_id  text not null references member,
  card_type  text not null check (card_type in ('PHYSICAL','DIGITAL','GUEST')),
  status     text not null default 'ACTIVE' check (status in ('ACTIVE','BLOCKED')),
  issued_at  timestamptz not null default now()
);

create table consent (
  member_id       text primary key references member on delete cascade,
  offers          boolean not null,              -- personalised offers and coupons
  profiling       boolean not null,              -- store and use purchase history
  digital_receipt boolean not null default false,
  policy_version  text not null,
  changed_at      timestamptz not null default now(),
  source          text not null check (source in ('seed','operator','pos'))
);

create table member_tag (
  member_id text not null references member on delete cascade,
  tag       text not null references tag_vocabulary,
  source    text not null check (source in ('EXPLICIT','DERIVED')),
  weight    numeric(3,2) not null default 1.00 check (weight > 0 and weight <= 1),
  primary key (member_id, tag)
);

create table account (
  account_id   text primary key,                 -- 'ACC-M-0001-POINTS'
  member_id    text not null references member,
  program_id   text not null references program,
  account_type text not null,
  balance      numeric(12,2) not null default 0 check (balance >= 0),
  unique (member_id, account_type)
);

-- Append-only ledger; the unique key makes ReportPurchase idempotent.
create table points_ledger (
  entry_id      bigserial primary key,
  account_id    text not null references account,
  purchase_transaction_id uuid,
  kind          text not null check (kind in ('EARN','REVERSAL','ADJUST','EXPIRE','BURN')),
  amount        numeric(12,2) not null,          -- signed
  balance_after numeric(12,2) not null check (balance_after >= 0),
  promotion_id  text,
  visit_id      text,                            -- set for booth runtime rows (reset)
  is_seed       boolean not null default false,
  created_at    timestamptz not null default now(),
  unique (purchase_transaction_id, account_id, kind)
);

create table offer (
  offer_id          text primary key,            -- 'OFF-CANTUCCINI-30'
  kind              text not null check (kind in
                      ('PERSONAL_COUPON','TIED_OFFER','CHECKOUT_COUPON','SPECIAL_COUPON')),
  target_article    text references article_ref, -- null = basket coupon
  condition_article text references article_ref, -- tied offer / checkout rule
  match_tags        text[] not null default '{}',
  discount_type     text not null check (discount_type in ('RELATIVE','ABSOLUTE','NEW_PRICE')),
  discount_value    numeric(8,2) not null check (discount_value > 0),
  max_discount_eur  numeric(6,2) not null check (max_discount_eur > 0),
  min_basket_eur    numeric(8,2) not null default 0,
  valid_days        int not null check (valid_days between 0 and 30),
  in_catalogue      boolean not null default true,
  approval          text not null default 'NONE' check (approval in ('NONE','HUMAN')),
  prefix            text,                        -- anonymous coupons: 'GPOS'
  promotion_code    text,                        -- reusable code of a tied offer
  promotion_id      text not null,               -- BaseDiscount.promotion_id
  text_key          text not null,
  priority          int not null default 100,
  active            boolean not null default true,
  -- catalogue caps (C02): auto-issuable offers stay within 30 % and 3.00 EUR
  check (approval = 'HUMAN' or (discount_type <> 'RELATIVE' or discount_value <= 30)),
  check (approval = 'HUMAN' or max_discount_eur <= 3.00),
  check (kind <> 'SPECIAL_COUPON' or approval = 'HUMAN'),
  check (kind <> 'TIED_OFFER' or (condition_article is not null and prefix is not null
                                  and promotion_code is not null))
);

create table coupon (
  coupon_id        text primary key,             -- 'CPN-0217-0042'
  coupon_code      text not null unique,         -- printed value (bearer secret)
  offer_id         text not null references offer,
  member_id        text references member,       -- null = anonymous coupon
  status           text not null default 'ISSUED'
                     check (status in ('ISSUED','REDEEMED','VOIDED','EXPIRED')),
  discount_type    text not null,                -- snapshot at issue
  discount_value   numeric(8,2) not null,
  max_discount_eur numeric(6,2) not null,
  target_article   text references article_ref,
  valid_from       timestamptz not null,
  valid_to         timestamptz not null,
  issued_channel   text not null check (issued_channel in ('RULE','AGENT','HUMAN_APPROVED','CHECKOUT')),
  issued_in_tx     uuid,
  proposal_id      text,
  approver_ref     text,                         -- role pseudonym, never a person
  sam_run_id       text,
  display_text     text check (length(display_text) <= 120),
  visit_id         text,
  issued_at        timestamptz not null default now(),
  redeemed_in_tx   uuid,
  redeemed_at      timestamptz,
  discount_granted_eur numeric(6,2),
  check (valid_to > valid_from),
  check ((status = 'REDEEMED') = (redeemed_in_tx is not null)),
  check (issued_channel <> 'HUMAN_APPROVED' or approver_ref is not null)
);
-- frequency rule: at most one open coupon per member and offer
create unique index coupon_one_open_per_member_offer
  on coupon (member_id, offer_id) where status = 'ISSUED' and member_id is not null;
create index coupon_member_status on coupon (member_id, status);

-- Purchases reported after closing (finality: never for cancelled baskets).
create table purchase (
  purchase_transaction_id uuid primary key,
  member_id        text references member,       -- null = anonymous
  receipt_number   text not null,
  location         text not null,                -- 'Root.DE.999.101.01'
  transaction_type text not null check (transaction_type in ('SALE','VOID')),
  referenced_purchase_transaction_id uuid,       -- for VOID
  closed_at        timestamptz not null,
  total_eur        numeric(10,2) not null,
  points_earned    numeric(12,2) not null default 0,
  visit_id         text,
  is_seed          boolean not null default false,
  reported_at      timestamptz not null default now(),
  check (transaction_type = 'SALE' or referenced_purchase_transaction_id is not null)
);

-- Lines are stored only with consent.profiling = true (data minimisation).
create table purchase_line (
  purchase_transaction_id uuid not null references purchase on delete cascade,
  position_id      text not null,
  article_number   text not null references article_ref,
  category         text not null,
  item_count       int not null,
  effective_value_eur numeric(10,2) not null,
  primary key (purchase_transaction_id, position_id)
);

-- GEBIT position ids per open transaction (from ResolveMembership / ResolveCoupon).
create table membership_assignment (
  purchase_transaction_id uuid not null,
  member_id        text not null references member,
  card_value       text not null,
  membership_position_id text,
  verified         boolean not null,
  resolved_at      timestamptz not null default now(),
  primary key (purchase_transaction_id, member_id)
);

-- Transactional outbox: rows are written in the same transaction as the state
-- change and published to Solace by the service loop, then marked.
create table event_outbox (
  id           bigserial primary key,
  aggregate_id text not null,                    -- member_id or coupon_id
  aggregate_offset bigint not null,              -- becomes metadata.offset
  event_type   text not null,                    -- 'CouponIssued'
  topic        text not null,
  payload      jsonb not null,                   -- proto3 JSON with @type
  created_at   timestamptz not null default now(),
  published_at timestamptz,
  unique (aggregate_id, aggregate_offset)
);
create index event_outbox_unpublished on event_outbox (id) where published_at is null;

create table audit (
  id      bigserial primary key,
  ts      timestamptz not null default now(),
  actor   text not null,                         -- 'pos-sim' | 'gpos-engine' | 'operator'
  action  text not null,                         -- 'IssueCoupon' ...
  ref     text,
  payload jsonb not null default '{}'
);

-- Agent-facing aggregates: history only with profiling consent (C05).
create view member_category_8w as
select m.member_id, l.category,
       count(distinct p.purchase_transaction_id)::int as purchases_8w,
       (current_date - max(p.closed_at)::date)::int   as days_since_last
from member m
join consent c on c.member_id = m.member_id and c.profiling
join purchase p on p.member_id = m.member_id
              and p.transaction_type = 'SALE'
              and p.closed_at >= now() - interval '56 days'
join purchase_line l on l.purchase_transaction_id = p.purchase_transaction_id
group by m.member_id, l.category;
