"""Built-in project label templates."""

from typing import TypedDict


class ClassTemplateItem(TypedDict):
    class_index: int
    name: str
    scientific_name: str
    state_name: str
    display_color: str


OCTOCORAL_TEMPLATE: tuple[ClassTemplateItem, ...] = (
    {
        "class_index": 0,
        "name": "Muricea Closed",
        "scientific_name": "Muricea pendula",
        "state_name": "Closed",
        "display_color": "#E76F51",
    },
    {
        "class_index": 1,
        "name": "Thesea Closed",
        "scientific_name": "Thesea nivea",
        "state_name": "Closed",
        "display_color": "#F4A261",
    },
    {
        "class_index": 2,
        "name": "Muricea Open",
        "scientific_name": "Muricea pendula",
        "state_name": "Open",
        "display_color": "#E9C46A",
    },
    {
        "class_index": 3,
        "name": "Swiftia Open",
        "scientific_name": "Swiftia exserta",
        "state_name": "Open",
        "display_color": "#2A9D8F",
    },
    {
        "class_index": 4,
        "name": "Swiftia Closed",
        "scientific_name": "Swiftia exserta",
        "state_name": "Closed",
        "display_color": "#457B9D",
    },
    {
        "class_index": 5,
        "name": "Thesea Open",
        "scientific_name": "Thesea nivea",
        "state_name": "Open",
        "display_color": "#9B5DE5",
    },
)
