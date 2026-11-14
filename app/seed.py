"""Demo workspace for a FICTIONAL brand, so judges can try the product without setup."""
import os

from .auth import hash_password

GUIDELINES = [
    ("Brand voice and tone", "Verdant's voice is warm, plain-spoken and optimistic. Avoid hype, all-caps shouting, more than one exclamation mark, and slang."),
    ("Health claims", "Never describe a product as healthy, a superfood, a detox or a cure. Only use nutrition claims that appear in the approved facts list."),
    ("Substantiating claims", "Every performance, health or sustainability claim must match an approved fact. If no approved fact supports a claim, do not publish it."),
    ("Competitor mentions", "Do not compare Verdant to named competitors or say we beat other brands. Talk about what our product does, not what others lack."),
    ("Brand name", "Always write the brand name as Verdant with a capital V. Product names are Verdant Oat Bars and Verdant Trail Mix."),
    ("Accessibility in copy", "Write in plain language. Do not use emoji in place of words, and keep hashtags to a maximum of three per post."),
    ("Calls to action", "Calls to action should be gentle and specific, such as 'Find us in stores' or 'Try the new flavour'. Avoid pressure phrases like 'buy now before it's gone'."),
]

FACTS = [
    ("Protein", "Verdant Oat Bars contain 6 g of protein per 40 g bar."),
    ("Sugar", "Verdant Oat Bars have no added refined sugar. Each bar contains 5 g of naturally occurring sugar from dates."),
    ("Packaging", "Verdant packaging is made from 70% recycled plastic. It is recyclable where soft-plastic recycling is available."),
    ("Availability", "Verdant launched in 2021 and is sold in India and the UAE."),
    ("Ingredients", "Verdant Oat Bars are made with whole rolled oats, dates, almonds and sunflower seeds. They contain nuts."),
]

TERMS = [
    ("snack bar", "oat bar", "Product wording", "Call the product an oat bar, not a snack bar."),
    ("cheap", "affordable", "Price wording", "Describe pricing as affordable, never cheap."),
    ("users", "customers", "Audience wording", "We speak to customers, not users."),
    ("VERDANT", "Verdant", "Brand name casing", "Always write the brand name as Verdant with a capital V.", True),
]

BANNED = [
    ("guaranteed", "Banned phrase", "Do not promise guaranteed results."),
    ("#1", "Banned phrase", "Do not claim to be number one without an approved fact."),
    ("best in the world", "Banned phrase", "Superlatives without an approved fact are not allowed."),
    ("superfood", "Banned phrase", "Never describe a product as a superfood."),
    ("detox", "Banned phrase", "Never describe a product as a detox."),
    ("sugar free", "Banned phrase", "Verdant Oat Bars contain natural sugar from dates, so they cannot be called sugar free."),
    ("100% recyclable", "Banned phrase", "Packaging is 70% recycled plastic and recyclable only where soft-plastic recycling exists."),
]

SAMPLE_DRAFT = (
    "VERDANT Oat Bars are the #1 healthiest snack bar in India!!! 100% sugar free and guaranteed to boost your "
    "energy all day. Our packaging is fully recyclable and better for the planet than any other brand. "
    "Way better than BarCo bars. Buy now before it's gone, users love it!"
)


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    pw = os.environ.get("DEMO_PASSWORD", "change-me-demo")
    for username, name, role in [
        ("admin", "Asha (Brand admin)", "admin"),
        ("creator", "Kabir (Content creator)", "creator"),
        ("reviewer", "Meera (Brand reviewer)", "reviewer"),
    ]:
        conn.execute("INSERT INTO users (username, name, role, pw_hash) VALUES (?,?,?,?)",
                     (username, name, role, hash_password(pw)))
    for title, body in GUIDELINES:
        conn.execute("INSERT INTO sources (kind, title, body) VALUES ('guideline',?,?)", (title, body))
    for title, body in FACTS:
        conn.execute("INSERT INTO sources (kind, title, body) VALUES ('fact',?,?)", (title, body))
    for t in TERMS:
        avoid, prefer, title, body = t[:4]
        cs = 1 if len(t) > 4 and t[4] else 0
        conn.execute("INSERT INTO sources (kind, title, body, avoid, prefer, case_sensitive) VALUES ('term',?,?,?,?,?)",
                     (title, body, avoid, prefer, cs))
    for avoid, title, body in BANNED:
        conn.execute("INSERT INTO sources (kind, title, body, avoid) VALUES ('banned',?,?,?)", (title, body, avoid))
    conn.commit()
