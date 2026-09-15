"""One-off regeneration of manual_confidence_spot_check.csv with a proper
CSV writer (csv.writer / QUOTE_MINIMAL), fixing a malformed row that pandas'
C parser could not tokenize (a `"` character inside an unquoted field on the
Chin Meshi 109 row broke column alignment from that row onward). Content is
unchanged from the original manual review -- only the encoding is fixed.
"""
import csv
from pathlib import Path

OUT = Path("data/prototype/danang_hoian_halo/audit/manual_confidence_spot_check.csv")

FIELDS = ["category", "band", "overture_id", "name", "confidence", "has_website", "has_phone", "web_search_verdict", "notes"]

ROWS = [
    ["food_drink", "high", "e80c77cc-09d0-4fcf-a47d-8cb6fc5b4c7b", "Hải Sản Family (Bé Hạnh) - Seafood restaurant", "0.924", "False", "True", "corroborated", "Found on monandanang.vn and danangcafes.com matching name and category"],
    ["food_drink", "high", "58fe6acc-9504-4405-bf7b-7655bbf571f8", "Dng.coffee", "0.995", "True", "True", "corroborated", "Tripadvisor + Facebook + multiple guides; exact address given (An Thuong 2)"],
    ["food_drink", "high", "4fd54edb-e758-4a43-8351-65f462808938", "Chin Meshi 109 - JackPot BBQ", "0.960", "False", "True", "corroborated_partial", "Chin Meshi 109 clearly real (Tripadvisor 4.7/5 #378); the \"JackPot BBQ\" portion is not independently confirmed as the same entity"],
    ["food_drink", "high", "ba2c8d19-0f06-486e-b4dd-4ee6e60eb808", "Esco Beach Bar Lounge & Restaurant", "0.989", "True", "True", "corroborated", "Dedicated website escobeach.com plus multiple review sites"],
    ["food_drink", "low", "c4cfea2e-db57-41f0-96b5-88c3d3174c97", "Bo'Bo Food", "0.251", "False", "True", "corroborated", "Tripadvisor + Facebook page (GreekBoBoFood) + Wanderlog; real food truck"],
    ["food_drink", "low", "b72424a4-e1d5-45ff-9970-b93c87a6d1f2", "Sữa chua Hạ Long", "0.228", "False", "True", "corroborated_partial", "Real nationwide chain (~300 stores) present in Da Nang; this specific outlet not individually confirmed"],
    ["food_drink", "low", "1bc9769b-4ab1-4a3d-820d-eb8a0838dbc5", "Xôi lá chuối dì Mơ", "0.106", "False", "True", "not_corroborated", "Dish/vendor type (\"xoi la chuoi\") is common in Da Nang but this specific named vendor was not found; lowest-confidence record in the sample"],
    ["food_drink", "low", "ec704963-a41b-41d0-be35-6157ea207223", "Lucky Coffee & Foods", "0.296", "False", "False", "weak", "Found similarly-named \"Lucky Cafe\" (Da Nang airport) and \"LU COFFEE\" but neither is an exact name match"],
    ["lodging", "high", "bfaeca69-4933-44f2-b35a-f28652dc4d07", "Betel Garden Villas", "0.993", "True", "True", "corroborated", "Own website + Booking.com + Tripadvisor (#105 of 462, 4/5) + MakeMyTrip"],
    ["lodging", "high", "88ea747c-c322-423b-b4ad-f109e66aaca0", "Little Hoi An Boutique Hotel and Spa", "0.997", "True", "True", "corroborated", "Own website (littlehoian.com) + Hotels.com/Expedia/Trip.com; 9.4/10 rating"],
    ["lodging", "high", "cc1b1dae-14ea-4d83-8310-0ff4fcbe141d", "Hanoi Center Hotel Apartment", "0.861", "False", "True", "not_corroborated", "Exact name not found; nearest matches were differently-named properties (\"Hana Hotel & Apartment Da Nang\", \"Hanoi Hotel Da Nang\") -- high confidence score did NOT guarantee easy web verification"],
    ["lodging", "high", "93ae24f6-410b-46df-b49e-a6501f49c63b", "Khách sạn Monaco", "0.757", "True", "True", "corroborated", "Booking.com + Agoda + Trip.com; beachfront hotel matching description"],
    ["lodging", "low", "364ed6e2-a3f6-4cdd-85d8-bf09c0752278", "Pearl Villa Danang Beach", "0.293", "True", "True", "corroborated", "Dedicated website pearlvilladanang.com; low confidence score did NOT mean unverifiable"],
    ["lodging", "low", "228f90c9-3f9c-45d6-abb1-8c720ac9548c", "Nhà trọ", "0.043", "False", "False", "not_corroborated", "Name is the generic Vietnamese common noun for \"boarding house\", not a proper name -- cannot be matched to a specific real business by search at all"],
    ["lodging", "low", "56f0c98a-603b-440c-a555-d6ecf4daf6e9", "Ai Nghia Homestay - Banh Mi Hoi An", "0.298", "False", "True", "corroborated", "Own Facebook page + Booking.com/Expedia/Hotels.com"],
    ["lodging", "low", "4f9a94ee-9e7b-4b53-a2fd-1c105626cc44", "Green Residence Hotel", "0.225", "False", "True", "corroborated_partial", "Closest match is greenresidence.vn (a distinct property from the similarly-named Green Garden Residence Hotel); naming ambiguity among similar properties in the area"],
]

with open(OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(FIELDS)
    writer.writerows(ROWS)

print(f"wrote {len(ROWS)} data rows to {OUT}")
