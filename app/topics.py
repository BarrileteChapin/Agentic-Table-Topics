import random

TABLE_TOPICS = [
    "A habit worth starting this month",
    "The best advice I ignored",
    "A place that changed how I see home",
    "Why small talk matters",
    "A skill I want and the first step toward it",
    "Something ordinary that deserves more credit",
    "A risk that paid off",
    "What I would tell my younger self about patience",
    "A tradition I would invent",
    "The last time I changed my mind",
    "Why finishing is harder than starting",
    "A person who taught me without meaning to",
    "What courage looks like on an ordinary Tuesday",
    "A tool I could not live without",
    "The case for being early",
    "A story behind a favorite meal",
    "What I learned from being wrong in public",
    "A city, real or imagined, I would spend a year in",
    "Why questions are better than answers",
    "Something I used to fear and do not anymore",
    "The gift of a good neighbor",
    "A book, film, or song that still works on me",
    "What I would put in a time capsule",
    "Why rest is part of the work",
]


def random_topic() -> str:
    return random.choice(TABLE_TOPICS)
