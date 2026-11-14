"""Pure parsers: auctions, WoW Forever auction houses and account characters."""
from custom_components.wow_blizzard.parsers import (
    cheapest_source,
    forever_auction_houses,
    forever_ruleset_factions,
    parse_account_characters,
    summarize_auctions,
)

# Auction house index of a WoW Forever ruleset (English names, as requested)
FOREVER_INDEX = {
    "auctions": [
        {"id": 110, "name": "Alliance Auction House"},
        {"id": 113, "name": "Horde Auction House"},
        {"id": 116, "name": "Blackwater Auction House"},
        {"id": "x", "name": "Broken entry"},
    ]
}


def test_summarize_auctions_commodities_and_stacks():
    """Commodities use unit_price, stacks the buyout per item; bids have no price."""
    data = {
        "auctions": [
            {"item": {"id": 2589}, "quantity": 20, "unit_price": 25},
            {"item": {"id": 2589}, "quantity": 5, "unit_price": 20},
            {"item": {"id": 2309}, "quantity": 2, "buyout": 1000},
            {"item": {"id": 2309}, "quantity": 1, "bid": 50},
            {"item": {"id": 4306}, "quantity": 1, "unit_price": 1},
        ]
    }
    result = summarize_auctions(data, {2589, 2309})
    assert result == {
        2589: {"min_price": 20, "quantity": 25, "auctions": 2},
        2309: {"min_price": 500, "quantity": 3, "auctions": 2},
    }
    assert summarize_auctions({}, {2589}) == {}


def test_cheapest_source():
    """Lowest priced source; sources without a price are skipped, ties keep the first."""
    assert cheapest_source({"A (110)": 30, "H (113)": 20, "B (116)": None}) == "H (113)"
    assert cheapest_source({"first": 5, "second": 5}) == "first"
    assert cheapest_source({"bids only": None}) is None
    assert cheapest_source({}) is None


def test_forever_ruleset_factions_mixed():
    """A character without a known faction needs every house of its ruleset."""
    assert forever_ruleset_factions([(2, "Normal", "ALLIANCE"), (2, "Normal", None)]) == {2: ("Normal", set())}
    # Order does not matter, and faction types are case-insensitive
    assert forever_ruleset_factions([(2, "Normal", ""), (2, "Normal", "alliance")]) == {2: ("Normal", set())}


def test_forever_ruleset_factions_per_ruleset():
    """Rulesets are separate; both factions in one ruleset; no ruleset is skipped."""
    result = forever_ruleset_factions([
        (2, "Normal", "ALLIANCE"),
        (2, "Normal", "HORDE"),
        (1, "PvP", None),
        (1, "PvP", "HORDE"),
        (None, "forever", "HORDE"),
        ("2", "Normal", "HORDE"),
    ])
    assert result == {2: ("Normal", {"ALLIANCE", "HORDE"}), 1: ("PvP", set())}


def test_forever_auction_houses():
    """Own faction plus neutral houses; every house without a faction."""
    assert [h["id"] for h in forever_auction_houses(FOREVER_INDEX, {"ALLIANCE"})] == [110, 116]
    assert [h["id"] for h in forever_auction_houses(FOREVER_INDEX, {"HORDE"})] == [113, 116]
    houses = forever_auction_houses(FOREVER_INDEX, set())
    assert [(h["id"], h["faction"]) for h in houses] == [(110, "ALLIANCE"), (113, "HORDE"), (116, "NEUTRAL")]
    assert forever_auction_houses({}, set()) == []


def test_parse_account_characters_forever():
    """Forever characters have a ruleset instead of a realm, and a surname."""
    data = {
        "wow_accounts": [{
            "id": 1,
            "characters": [
                {"name": "Thrall", "id": 10, "level": 80, "realm": {"id": 1001, "name": "Stormrage", "slug": "stormrage"}},
                {"name": "Jaina", "surname": "Proudmoore", "id": 11, "ruleset": {"id": 2, "name": "Normal"}},
                {"name": "Arthas", "surname": "Menethil", "id": 12},
            ],
        }]
    }
    retail, forever, unknown = parse_account_characters(data)
    assert (retail["realm_slug"], retail["realm_id"], retail["ruleset_id"]) == ("stormrage", 1001, None)
    assert (forever["name"], forever["realm_slug"], forever["ruleset_id"]) == ("Jaina Proudmoore", "normal", 2)
    # Without a ruleset in the account list: realm "forever" and no ruleset,
    # which store_forever_rulesets fills in from the profile later
    assert (unknown["realm_slug"], unknown["ruleset_id"]) == ("forever", None)
