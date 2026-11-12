"""D-FINE object detector trained on Objects365: 365 kinds of things and animals, with boxes.

The ONNX export takes the photo resized to 640×640 (no padding, RGB scaled to 0..1) and returns
300 queries with a score per class (sigmoid) and a box (centre x, centre y, width, height, all
0..1). A query's best classes above the floor become detections; class 0 ("None") never does.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .runtime import session

SIZE = 640
OBJ_V = 1  # version of the objects pass (media.obj_v); photos below it are read again
MIN_SCORE = 0.25  # stored from here; categories, search and pets set their own bars higher

# Objects365 classes in the model's order (index 0 is the model's "None")
LABELS: tuple[str, ...] = (
    "None", "Person", "Sneakers", "Chair", "Other Shoes", "Hat", "Car", "Lamp", "Glasses", "Bottle", "Desk", "Cup",
    "Street Lights", "Cabinet/shelf", "Handbag/Satchel", "Bracelet", "Plate", "Picture/Frame", "Helmet", "Book", "Gloves",
    "Storage box", "Boat", "Leather Shoes", "Flower", "Bench", "Potted Plant", "Bowl/Basin", "Flag", "Pillow", "Boots",
    "Vase", "Microphone", "Necklace", "Ring", "SUV", "Wine Glass", "Belt", "Monitor/TV", "Backpack", "Umbrella",
    "Traffic Light", "Speaker", "Watch", "Tie", "Trash bin Can", "Slippers", "Bicycle", "Stool", "Barrel/bucket", "Van",
    "Couch", "Sandals", "Basket", "Drum", "Pen/Pencil", "Bus", "Wild Bird", "High Heels", "Motorcycle", "Guitar",
    "Carpet", "Cell Phone", "Bread", "Camera", "Canned", "Truck", "Traffic cone", "Cymbal", "Lifesaver", "Towel",
    "Stuffed Toy", "Candle", "Sailboat", "Laptop", "Awning", "Bed", "Faucet", "Tent", "Horse", "Mirror", "Power outlet",
    "Sink", "Apple", "Air Conditioner", "Knife", "Hockey Stick", "Paddle", "Pickup Truck", "Fork", "Traffic Sign",
    "Balloon", "Tripod", "Dog", "Spoon", "Clock", "Pot", "Cow", "Cake", "Dinning Table", "Sheep", "Hanger",
    "Blackboard/Whiteboard", "Napkin", "Other Fish", "Orange/Tangerine", "Toiletry", "Keyboard", "Tomato", "Lantern",
    "Machinery Vehicle", "Fan", "Green Vegetables", "Banana", "Baseball Glove", "Airplane", "Mouse", "Train", "Pumpkin",
    "Soccer", "Skiboard", "Luggage", "Nightstand", "Tea pot", "Telephone", "Trolley", "Head Phone", "Sports Car",
    "Stop Sign", "Dessert", "Scooter", "Stroller", "Crane", "Remote", "Refrigerator", "Oven", "Lemon", "Duck",
    "Baseball Bat", "Surveillance Camera", "Cat", "Jug", "Broccoli", "Piano", "Pizza", "Elephant", "Skateboard",
    "Surfboard", "Gun", "Skating and Skiing shoes", "Gas stove", "Donut", "Bow Tie", "Carrot", "Toilet", "Kite",
    "Strawberry", "Other Balls", "Shovel", "Pepper", "Computer Box", "Toilet Paper", "Cleaning Products", "Chopsticks",
    "Microwave", "Pigeon", "Baseball", "Cutting/chopping Board", "Coffee Table", "Side Table", "Scissors", "Marker",
    "Pie", "Ladder", "Snowboard", "Cookies", "Radiator", "Fire Hydrant", "Basketball", "Zebra", "Grape", "Giraffe",
    "Potato", "Sausage", "Tricycle", "Violin", "Egg", "Fire Extinguisher", "Candy", "Fire Truck", "Billiards",
    "Converter", "Bathtub", "Wheelchair", "Golf Club", "Briefcase", "Cucumber", "Cigar/Cigarette", "Paint Brush", "Pear",
    "Heavy Truck", "Hamburger", "Extractor", "Extension Cord", "Tong", "Tennis Racket", "Folder", "American Football",
    "earphone", "Mask", "Kettle", "Tennis", "Ship", "Swing", "Coffee Machine", "Slide", "Carriage", "Onion",
    "Green beans", "Projector", "Frisbee", "Washing Machine/Drying Machine", "Chicken", "Printer", "Watermelon",
    "Saxophone", "Tissue", "Toothbrush", "Ice cream", "Hot-air balloon", "Cello", "French Fries", "Scale", "Trophy",
    "Cabbage", "Hot dog", "Blender", "Peach", "Rice", "Wallet/Purse", "Volleyball", "Deer", "Goose", "Tape", "Tablet",
    "Cosmetics", "Trumpet", "Pineapple", "Golf Ball", "Ambulance", "Parking meter", "Mango", "Key", "Hurdle",
    "Fishing Rod", "Medal", "Flute", "Brush", "Penguin", "Megaphone", "Corn", "Lettuce", "Garlic", "Swan", "Helicopter",
    "Green Onion", "Sandwich", "Nuts", "Speed Limit Sign", "Induction Cooker", "Broom", "Trombone", "Plum", "Rickshaw",
    "Goldfish", "Kiwi fruit", "Router/modem", "Poker Card", "Toaster", "Shrimp", "Sushi", "Cheese", "Notepaper",
    "Cherry", "Pliers", "CD", "Pasta", "Hammer", "Cue", "Avocado", "Hamimelon", "Flask", "Mushroom", "Screwdriver",
    "Soap", "Recorder", "Bear", "Eggplant", "Board Eraser", "Coconut", "Tape Measure/Ruler", "Pig", "Showerhead",
    "Globe", "Chips", "Steak", "Crosswalk Sign", "Stapler", "Camel", "Formula 1", "Pomegranate", "Dishwasher", "Crab",
    "Hoverboard", "Meat ball", "Rice Cooker", "Tuba", "Calculator", "Papaya", "Antelope", "Parrot", "Seal", "Butterfly",
    "Dumbbell", "Donkey", "Lion", "Urinal", "Dolphin", "Electric Drill", "Hair Dryer", "Egg tart", "Jellyfish",
    "Treadmill", "Lighter", "Grapefruit", "Game board", "Mop", "Radish", "Baozi", "Target", "French", "Spring Rolls",
    "Monkey", "Rabbit", "Pencil Case", "Yak", "Red Cabbage", "Binoculars", "Asparagus", "Barbell", "Scallop", "Noddles",
    "Comb", "Dumpling", "Oyster", "Table Tennis paddle", "Cosmetics Brush/Eyeliner Pencil", "Chainsaw", "Eraser",
    "Lobster", "Durian", "Okra", "Lipstick", "Cosmetics Mirror", "Curling", "Table Tennis",
)
CLASS = {n: i for i, n in enumerate(LABELS)}

# How things are called in RecPro where Objects365's own name is odd (the rest: sentence case)
NAMES: dict[str, str] = {
    "Other Shoes": "Shoes", "Leather Shoes": "Shoes", "Cabinet/shelf": "Cabinet", "Handbag/Satchel": "Handbag",
    "Picture/Frame": "Picture frame", "Bowl/Basin": "Bowl", "Monitor/TV": "TV or monitor", "Trash bin Can": "Dustbin",
    "Barrel/bucket": "Bucket", "Pen/Pencil": "Pen", "Wild Bird": "Bird", "Cell Phone": "Mobile phone",
    "Dinning Table": "Dining table", "Other Fish": "Fish", "Orange/Tangerine": "Orange", "Blackboard/Whiteboard": "Board",
    "Skiboard": "Skis", "Head Phone": "Headphones", "Skating and Skiing shoes": "Skates", "Computer Box": "Desktop computer",
    "Cutting/chopping Board": "Cutting board", "Cigar/Cigarette": "Cigarette", "Extractor": "Kitchen chimney", "Tong": "Tongs",
    "earphone": "Earphones", "Tennis": "Tennis ball", "Washing Machine/Drying Machine": "Washing machine",
    "Hamimelon": "Melon", "Formula 1": "Racing car", "Noddles": "Noodles", "French": "French horn",
    "Router/modem": "Wi-Fi router", "Tape Measure/Ruler": "Ruler", "Cosmetics Brush/Eyeliner Pencil": "Makeup brush",
    "Wallet/Purse": "Wallet", "Table Tennis": "Table tennis ball", "Table Tennis paddle": "Table tennis bat",
    "Curling": "Curling stone", "Soccer": "Football", "Other Balls": "Ball", "Canned": "Can", "Lifesaver": "Life buoy",
    "Machinery Vehicle": "Construction vehicle", "Green Vegetables": "Vegetables", "Storage box": "Box",
    "Power outlet": "Power socket", "Poker Card": "Playing cards", "Game board": "Board game", "Scale": "Weighing scale",
    "Heavy Truck": "Lorry", "Toiletry": "Toiletries", "Notepaper": "Notepad", "Paint Brush": "Paintbrush",
    "Electric Drill": "Drill", "Induction Cooker": "Induction cooktop", "Meat ball": "Meatballs", "Green Onion": "Spring onion",
    "Street Lights": "Street light", "Stuffed Toy": "Soft toy", "Coffee Machine": "Coffee machine", "Hot-air balloon": "Hot air balloon",
    "Sneakers": "Shoes", "Gun": "Gun", "Trolley": "Trolley", "CD": "CD", "SUV": "SUV",
}


def display(cls: int) -> str:
    """A class's name as RecPro shows it ("Mobile phone", "Dining table")."""
    n = LABELS[cls]
    if n in NAMES:
        return NAMES[n]
    return n[:1].upper() + n[1:].lower()


@dataclass
class Obj:
    cls: int
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 as fractions of the photo

    @property
    def area(self) -> float:
        return max(0.0, self.box[2] - self.box[0]) * max(0.0, self.box[3] - self.box[1])


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))  # no overflow for large negative logits


def decode(logits: np.ndarray, boxes: np.ndarray, min_score: float = MIN_SCORE, top: int = 300) -> list[Obj]:
    """One photo's (queries × classes) logits and (queries × 4) boxes into detections, best first."""
    p = _sigmoid(logits.astype(np.float32))
    p[:, 0] = 0.0
    flat = p.reshape(-1)
    k = min(top, flat.size - 1)
    idx = np.argpartition(-flat, k)[:k]
    idx = idx[flat[idx] >= min_score]
    idx = idx[np.argsort(-flat[idx])]
    q, c = np.divmod(idx, p.shape[1])
    cx, cy, w, h = (boxes[q].astype(np.float32).T if len(q) else np.zeros((4, 0), np.float32))
    x1, y1 = np.clip(cx - w / 2, 0, 1), np.clip(cy - h / 2, 0, 1)
    x2, y2 = np.clip(cx + w / 2, 0, 1), np.clip(cy + h / 2, 0, 1)
    return [
        Obj(int(c[i]), float(flat[idx[i]]), (float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i])))
        for i in range(len(idx))
        if x2[i] > x1[i] and y2[i] > y1[i]
    ]


class ObjectDetector:
    def __init__(self, path: Path, use_gpu: bool = True):
        self.sess = session(path, use_gpu)
        self.inp = self.sess.get_inputs()[0].name
        names = [o.name for o in self.sess.get_outputs()]
        self._out = [names.index("logits"), names.index("pred_boxes")] if "logits" in names else [0, 1]

    @staticmethod
    def prepare(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        x = cv2.resize(img, (SIZE, SIZE), interpolation=cv2.INTER_AREA if max(h, w) > SIZE else cv2.INTER_LINEAR)
        return (x.astype(np.float32) * np.float32(1 / 255.0)).transpose(2, 0, 1)

    def detect_many(self, images: list[np.ndarray | None], min_score: float = MIN_SCORE, batch: int = 8) -> list[list[Obj]]:
        out: list[list[Obj]] = [[] for _ in images]
        todo = [i for i, im in enumerate(images) if im is not None]
        for s in range(0, len(todo), batch):
            chunk = todo[s : s + batch]
            blob = np.stack([self.prepare(images[i]) for i in chunk])  # type: ignore[arg-type]
            res = self.sess.run(None, {self.inp: blob})
            logits, boxes = res[self._out[0]], res[self._out[1]]
            for k, i in enumerate(chunk):
                out[i] = decode(logits[k], boxes[k], min_score)
        return out

    def detect(self, img: np.ndarray, min_score: float = MIN_SCORE) -> list[Obj]:
        return self.detect_many([img], min_score)[0]
