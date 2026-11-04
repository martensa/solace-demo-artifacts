"""Fictional instrument universe of the demo.

Three fictional issuers (alpha, beta, gamma), five products each in
three product classes. No real issuer or product names; ISINs follow
the demo pattern DE000DEMO0001 (deliberately NOT valid ISINs).
"""

from __future__ import annotations

from dataclasses import dataclass

ISSUERS = ("alpha", "beta", "gamma")
PRODUCT_CLASSES = ("dax-turbo", "nasdaq-knockout", "discount-cert")

# underlying slug -> (display name, start reference level)
UNDERLYINGS = {
    "dax": ("DAX-Index (Demo)", 19000.0),
    "nasdaq100": ("NASDAQ-100-Index (Demo)", 21000.0),
    "eurostoxx50": ("EURO-STOXX-50-Index (Demo)", 5000.0),
}

CLASS_UNDERLYING = {
    "dax-turbo": "dax",
    "nasdaq-knockout": "nasdaq100",
    "discount-cert": "eurostoxx50",
}

# products per issuer and class
LAYOUT = (("dax-turbo", 2), ("nasdaq-knockout", 2), ("discount-cert", 1))


@dataclass(frozen=True)
class Product:
    issuer: str
    isin: str
    product_class: str
    underlying: str
    # price model: price = ratio * (ref - strike) for turbos/knock-outs,
    # ratio * min(ref, cap) * discount for discount certificates
    ratio: float
    strike: float
    cap: float
    base_spread_pct: float


def _build() -> tuple[Product, ...]:
    products = []
    n = 0
    # deterministic, reproducible parameters (no RNG at import time)
    for i_idx, issuer in enumerate(ISSUERS):
        for pclass, count in LAYOUT:
            for k in range(count):
                n += 1
                und = CLASS_UNDERLYING[pclass]
                ref = UNDERLYINGS[und][1]
                strike = ref * (0.90 - 0.03 * k - 0.01 * i_idx)
                products.append(
                    Product(
                        issuer=issuer,
                        isin=f"DE000DEMO{n:04d}",
                        product_class=pclass,
                        underlying=und,
                        ratio=0.01,
                        strike=round(strike, 2),
                        cap=round(ref * (1.05 + 0.02 * k), 2),
                        # 0.10 .. 0.30 % normal spread
                        base_spread_pct=round(0.12 + 0.05 * k + 0.04 * i_idx, 3),
                    )
                )
    return tuple(products)


PRODUCTS: tuple[Product, ...] = _build()
BY_ISIN = {p.isin: p for p in PRODUCTS}


def fair_price(p: Product, ref: float) -> float:
    if p.product_class == "discount-cert":
        return round(p.ratio * min(ref, p.cap) * 0.97, 4)
    return round(max(p.ratio * (ref - p.strike), 0.001), 4)


def peers(issuer: str) -> list[str]:
    return [i for i in ISSUERS if i != issuer]
