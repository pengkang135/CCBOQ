#!/usr/bin/env python3
"""
BOQ Classification Engine
Routes each data row to Discipline → Category → Subcategory → Element using:
1. Section-level routing (L1 heading → Discipline)
2. Keyword + rule-based matching against norms DB closed vocabulary
3. Fallback for unmatched items (output to JSON for LLM review)
"""
import sqlite3
import json
import re
from pathlib import Path
from collections import defaultdict

# ── Norms DB paths ──────────────────────────────────────
DB_DIR = Path(r"E:\Code\Norms-AI\db")
BOOKS = {
    "A": DB_DIR / "企业定额_A册_建筑装饰.sqlite",
    "B": DB_DIR / "企业定额_B册_通用安装.sqlite",
    "C": DB_DIR / "企业定额_C册_市政园林.sqlite",
    "D": DB_DIR / "企业定额_D册_水运工程.sqlite",
    "E": DB_DIR / "企业定额_E册_房屋修缮.sqlite",
}

# ── Section → (Discipline, Discipline_EN) routing ───────
SECTION_ROUTING = {
    "A_Prelims": ("开办费", "Preliminaries"),
    "B_Prep Works": ("A", "Civil & Decoration"),  # demolition/site prep
    "C_Dredging": ("D", "Water Transport Engineering"),
    "D_Rec'n GI & EW": ("D", "Water Transport Engineering"),  # reclamation, ground improvement
    "E_Quay _STEEL": ("D", "Water Transport Engineering"),  # quay wall, marine structures
    "F_Yard Civil & Structural": ("A", "Civil & Decoration"),  # yard civil, buildings
    "G_Electrical , IT & Mechanical": ("B", "General Installation"),  # MEP
    "H_Buildings": ("A", "Civil & Decoration"),
    "I_Gate Complex": ("A", "Civil & Decoration"),
}

# ── L2 section → Category mapping (for batch classification) ──
L2_CATEGORY_MAP = {
    # D_Rec'n GI & EW — removed "Ground Improvement" from L2 map: items need D-volume
    # classification via keyword matching, not forced to A.02

    # F_Yard Civil
    "Pavements (PER 006A)": ("A.31", "External Site Works", "01", "External Site Works (incl. roads, levelling)"),
    "Storm Water Drainage system (PER 006B)": ("A.31", "External Site Works", "01", "External Site Works (incl. roads, levelling)"),
    "Electrical Services (civil works) (PER 006C)": ("A.32", "Builders' Work in Connection with Services", "", ""),
    "Reefer Racks and Foundations (PER 006D)": ("A.07", "Metal Structures and Components", "", ""),
    "Leaking Container Bund (PER 006E)": ("A.04", "Cast-in-place Concrete and Reinforcement", "", ""),
    "Light Tower & CCTV Tower Foundations (PER 006F)": ("A.04", "Cast-in-place Concrete and Reinforcement", "", ""),
    "Fencing and Barriers (PER 006G)": ("A.31", "External Site Works", "01", "External Site Works (incl. roads, levelling)"),
    "Linemarking and Signage (PER 006J)": ("A.31", "External Site Works", "02", "Road Markings and Signage"),
    "RTG storm tie-down": ("A.07", "Metal Structures and Components", "", ""),
    # E_Quay Steel
    "Front Cap Beam Work Quantity (Steel Pipe Pile Scheme)\nL = 613m, frame spacing 7.57m": ("D.06", "Concrete Works", "", ""),
    "Rear pile cap": ("D.06", "Concrete Works", "", ""),
    "Quay Linemarking (PER 005J)": ("A.31", "External Site Works", "02", "Road Markings and Signage"),
    "STS Crane Furniture (PER 005D)": ("A.04", "Cast-in-place Concrete and Reinforcement", "", ""),
    "Shore connection and foundation treatment": ("A.31", "External Site Works", "01", "External Site Works (incl. roads, levelling)"),
    # "Coner plateform" removed from L2 map: contains mixed items (PHC piles, steel piles,
    # concrete grouting, pile caps) not just anti-corrosion. Let keyword matching handle each item.
    "Excavation and protection under the front and rear pier caps (excluding parts inside the dock basin)": ("D.06", "Concrete Works", "", ""),
    # G_Electrical
    "HV Cabling": ("B.04", "Electrical Equipment Installation Works", "03", "Power Cabling"),
    "LV Cabling - External to substations": ("B.04", "Electrical Equipment Installation Works", "03", "Power Cabling"),
    "Main Substation": ("B.04", "Electrical Equipment Installation Works", "01", "High Voltage Equipment"),
    "Lighting (Please refer to single-line diagram APM-056-07C-02)": ("B.04", "Electrical Equipment Installation Works", "06", "Lighting and Small Power"),
    "IT Network and Security (PER 007F)": ("B.11", "Telecommunications Equipment and Cabling Works", "", ""),
    "Firewater Services (PER 007K)": ("B.09", "Fire Protection Works", "02", "Fire Hydrant and Hose Reel Systems"),
    "Reefer Power Supply (See details in single-line diagram APM-056-07I-05)": ("B.04", "Electrical Equipment Installation Works", "02", "Low Voltage Distribution"),
    "STS Pits (Please refer to STS PITS drawing APM-056-05D-04 for details.)": ("B.04", "Electrical Equipment Installation Works", "02", "Low Voltage Distribution"),
    "eRTG Power Supply": ("B.04", "Electrical Equipment Installation Works", "02", "Low Voltage Distribution"),
    "Equipotential bonding": ("B.04", "Electrical Equipment Installation Works", "05", "Earthing and Lightning Protection"),
}


# ── Load closed vocabulary ───────────────────────────────
def load_vocab():
    """Load all divisions, sub_divisions, and chapters from norms DB."""
    vocab = {}
    for book, path in BOOKS.items():
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()

        # Divisions (Category)
        divisions = {}
        cur.execute("SELECT code, name, name_EN FROM division ORDER BY code")
        for code, name, name_en in cur.fetchall():
            divisions[code] = {"name": name, "name_en": name_en or name}
        vocab[book] = {"divisions": divisions, "sub_divisions": {}, "items": {}}

        # Sub-divisions (Subcategory)
        try:
            cur.execute("SELECT division_code, code, name, name_EN FROM sub_division ORDER BY division_code, code")
            rows = cur.fetchall()
            for div_code, code, name, name_en in rows:
                if div_code not in vocab[book]["sub_divisions"]:
                    vocab[book]["sub_divisions"][div_code] = {}
                vocab[book]["sub_divisions"][div_code][code] = {
                    "name": name,
                    "name_en": name_en or name,
                }
        except sqlite3.OperationalError:
            pass

        # Enterprise items / chapters (Element)
        try:
            cur.execute("SELECT code, name, name_EN FROM enterprise_item ORDER BY code")
            rows = cur.fetchall()
            for code, name, name_en in rows:
                vocab[book]["items"][code] = {"name": name, "name_en": name_en or name}
        except sqlite3.OperationalError:
            pass

        conn.close()
    return vocab


# ── Rules from classification_rules.json ─────────────────
PATTERNS = [
    (re.compile(r"masonry construction of slurry pit", re.I),
     "A", "A.06", "Masonry Works", "", ""),
    (re.compile(r"anti.?termite|termite.?treatment|termite.?control", re.I),
     "A", "A.01", "Site Preparation and Earthworks", "03", "Site Preparation and Others"),
    (re.compile(r"accessibility sign", re.I),
     "A", "A.24", "Miscellaneous Decoration and Furniture Fittings", "07", "Signage and Light Boxes"),
    (re.compile(r"fire.?stopp|fire.?resist|fire.?proof|fire.?seal", re.I),
     "A", "A.12", "Thermal Insulation, Fire Protection and Corrosion Protection", "01", "Thermal and Acoustic Insulation"),
    (re.compile(r"flame.?retardant extruded polystyrene|xps.*(flame|thermal)|extruded polystyrene.*(insulation|board)(?!.*protection)", re.I),
     "A", "A.12", "Thermal Insulation, Fire Protection and Corrosion Protection", "01", "Thermal and Acoustic Insulation"),
    (re.compile(r"demolition|demolish|breaking|removal.*existing", re.I),
     "A", "A.30", "Demolition, Alteration and Repair", "", ""),
]

PROVISIONAL_SUMS = {
    "CONCRETE WORKS": ("A", "A.04", "Cast-in-place Concrete and Reinforcement", "", ""),
    "PRECAST REINFORCED CONCRETE WORKS": ("A", "A.05", "Precast Concrete and Prefabricated Construction", "", ""),
    "STRUCTURAL STEEL WORKS": ("A", "A.07", "Metal Structures and Components", "", ""),
    "PARTITION WORKS": ("A", "A.21", "Wall, Column Finishes and Partitions", "06", "Partitions and Screens"),
    "WATERPROOFING WORKS": ("A", "A.11", "Waterproofing and Damp-proofing", "", ""),
    "METAL WORKS": ("A", "A.07", "Metal Structures and Components", "", ""),
    "FLOOR FINISHES": ("A", "A.20", "Floor Finishes", "", ""),
    "WALL FINISHES": ("A", "A.21", "Wall, Column Finishes and Partitions", "", ""),
    "CEILING FINISHES": ("A", "A.22", "Ceiling Works", "", ""),
    "ROOFING WORKS": ("A", "A.10", "Roofing Works", "", ""),
    "OTHER WORKS": ("A", "A.12", "Thermal Insulation, Fire Protection and Corrosion Protection", "01", "Thermal and Acoustic Insulation"),
    "EXTERNAL WORK": ("A", "A.31", "External Site Works", "01", "External Site Works (incl. roads, levelling)"),
    "PLUMBING AND DRAINAGE SYSTEM": ("B", "B.10", "Plumbing, Heating and Gas Works", "01", "Plumbing, Heating and Gas Pipelines"),
}


# ── A-book keyword matching ──────────────────────────────
A_KEYWORDS = [
    # (regex, category_code, category_name_en, subcategory_code, subcategory_name_en)
    # A.01 Site Preparation
    (re.compile(r"ground clearance|site clearance|clearing|grubbing|stripping.*top.?soil", re.I),
     "A.01", "Site Preparation and Earthworks", "03", "Site Preparation and Others"),
    (re.compile(r"excavation|earthwork|cut.*fill|filling|embankment|backfill(?!.*trench.*pipe)", re.I),
     "A.01", "Site Preparation and Earthworks", "01", "Earthworks and Excavation"),
    (re.compile(r"(geotextile|geogrid|geocomposite|geomembrane)(?!.*drain)", re.I),
     "A.01", "Site Preparation and Earthworks", "03", "Site Preparation and Others"),

    # A.02 Ground Treatment
    (re.compile(r"soil improvement|ground improvement|soil treatment|compaction.*ground|settlement.*(treatment|case)|surcharge|pre.?loading|sand.*drain|wick.*drain|vertical.*drain|PVD|prefabricated.*drain|dynamic compaction|vibro.*compaction|stone.*colum|sand.*pile|sand.*compaction", re.I),
     "A.02", "Ground Treatment and Slope Support", "01", "Ground Treatment"),

    # A.03 Piling
    (re.compile(r"pile|piling|bored.*pile|driven.*pile|sheet.*pile|pile.*cap|king.*post|soldier.*pile|contiguous.*pile", re.I),
     "A.03", "Piling Works", "", ""),

    # A.04 Concrete
    (re.compile(r"concrete.*(slab|beam|column|wall|pile|foundation|footing|plinth|base|grade|floor|deck|pavement|paving)|reinforced concrete|RC.*(slab|beam|column|wall|structure)|in.?situ.*concrete|cast.?in.?place.*concrete|prestressed.*concrete|concrete.*reinforcement|rebar|steel.*reinforcement.*concrete|formwork|shuttering", re.I),
     "A.04", "Cast-in-place Concrete and Reinforcement", "", ""),
    (re.compile(r"concrete(?!.*(slab|beam|column|wall|pile|foundation|footing|plinth|base|grade|floor|deck|pavement|paving|reinforcement|rebar|formwork|shuttering))", re.I),
     "A.04", "Cast-in-place Concrete and Reinforcement", "", ""),

    # A.05 Precast
    (re.compile(r"precast|pre.?cast|prefabricated.*concrete|pre.?stressed|prestressed.*beam|precast.*(slab|beam|column|pile|panel|element|unit)", re.I),
     "A.05", "Precast Concrete and Prefabricated Construction", "", ""),

    # A.06 Masonry
    (re.compile(r"masonry|brick.*(work|wall)|block.*(work|wall)|blockwork|brickwork|concrete.*block.*(wall|work)|hollow.*block|solid.*block|rendering|plastering.*(mortar|cement)", re.I),
     "A.06", "Masonry Works", "", ""),

    # A.07 Steel/Metal
    (re.compile(r"structural steel|steel.*(frame|structure|beam|column|truss|deck|platform|stair|ladder|handrail|railing|balustrade|canopy|shed|roof)|metal.*(structure|frame|deck|cladding|sheet|roof|door|window)", re.I),
     "A.07", "Metal Structures and Components", "", ""),

    # A.08 Timber
    (re.compile(r"timber|wood.*(beam|column|frame|structure|deck|floor|door|window)|plywood|carpentry", re.I),
     "A.08", "Timber Structures and Carpentry", "", ""),

    # A.10 Roofing
    (re.compile(r"roofing|roof.*(cover|sheet|tile|panel|deck|structure|steel|metal|finish)|standing.*seam|kalzip|metal.*roof", re.I),
     "A.10", "Roofing Works", "", ""),

    # A.11 Waterproofing
    (re.compile(r"waterproof|water.?proof|damp.?proof|tanking|sealant(?!.*fire)|joint.*seal|water.?bar|waterstop(?!.*fire)|penetration.*seal(?!.*fire)", re.I),
     "A.11", "Waterproofing and Damp-proofing", "", ""),

    # A.12 Insulation / Fire Protection / Corrosion
    (re.compile(r"thermal.*insulation|insulation.*(board|slab|material|layer)|heat.*insulation|EPS|XPS(?!.*protection)|rock.?wool|mineral.*wool", re.I),
     "A.12", "Thermal Insulation, Fire Protection and Corrosion Protection", "01", "Thermal and Acoustic Insulation"),
    (re.compile(r"corrosion.*(protection|coating)|anti.?corrosion|rust.*proof|cathodic", re.I),
     "A.12", "Thermal Insulation, Fire Protection and Corrosion Protection", "02", "Anti-corrosion Protection"),

    # A.13 Doors & Windows
    (re.compile(r"door(?!.*fire)|window|roller.*shutter|ironmongery|hardware.*(door|window)|glazing(?!.*curtain)", re.I),
     "A.13", "Doors, Windows and Railings", "", ""),

    # A.14 Curtain Walls
    (re.compile(r"curtain.*wall|cladding|fa.?ade|external.*wall.*(system|panel|finish)", re.I),
     "A.14", "Curtain Walls and External Wall Finishes", "", ""),

    # A.20 Floor Finishes
    (re.compile(r"floor.*finish|screed|floor.*tile|carpet|vinyl.*floor|epoxy.*floor|resin.*floor|terrazzo|polished.*concrete.*floor|floor.*paint", re.I),
     "A.20", "Floor Finishes", "", ""),

    # A.21 Wall Finishes
    (re.compile(r"wall.*finish|wall.*tile|plaster(?!.*concrete)|render(?!.*concrete)|wall.*paint.*internal|partition(?!.*glass)|dry.?wall|gypsum.*board.*(wall|partition)", re.I),
     "A.21", "Wall, Column Finishes and Partitions", "", ""),

    # A.22 Ceiling
    (re.compile(r"ceiling|suspended.*ceiling|false.*ceiling|ceiling.*(tile|panel|board|finish)", re.I),
     "A.22", "Ceiling Works", "", ""),

    # A.23 Painting
    (re.compile(r"paint(?!.*floor)|coating(?!.*corrosion)(?!.*fire)|decoration.*paint|emulsion|varnish", re.I),
     "A.23", "Painting, Coatings and Wallcovering", "", ""),

    # A.24 Misc Decoration
    (re.compile(r"sign(?!.*design)|signage|toilet.*(partition|cubicle)|furniture|fixture.*fitting|sanitary.*(ware|fitting)|WC|urinal|wash.?basin|sink(?!.*kitchen)|toilet.*accessor|mirror|grab.*bar|locker|bench|seat", re.I),
     "A.24", "Miscellaneous Decoration and Furniture Fittings", "", ""),

    # A.30 Demolition
    (re.compile(r"demolition|demolish|break.?up.*existing|remove.*existing.*(structure|building|wall|fence|pavement|concrete)", re.I),
     "A.30", "Demolition, Alteration and Repair", "01", "Demolition Works"),

    # A.31 External Works
    (re.compile(r"paving(?!.*concrete.*structure)|road.*(base|sub.?base|asphalt|bitumen|tarmac|surface|pavement)|kerb|edging|drainage.*(channel|ditch|culvert)|manhole|catch.?pit|gully|road.*marking|line.*marking|fencing|gate(?!.*valve)|boundary.*wall|landscaping|planting|turf|grass|tree|shrub|retaining.*wall(?!.*piling)|guard.*rail|crash.*barrier", re.I),
     "A.31", "External Site Works", "", ""),

    # A.07 Metal Structures (extended)
    (re.compile(r"handrail|guard.?rail.*steel|steel.*handrail|railing.*steel|balustrade.*steel", re.I),
     "A.07", "Metal Structures and Components", "", ""),

    # A.14 Steel Structure (buildings, sheds)
    (re.compile(r"lashing.*storage|storage.*shed|steel.*shed|steel.*storage|container.*shed", re.I),
     "A.14", "Steel Structure Works", "01", "Steel Structure"),

    # A.04 Concrete (foundation cushion layer)
    (re.compile(r"foundation.*cushion|cushion.*layer.*foundation|generator.*foundation|load.*bank.*foundation", re.I),
     "A.04", "Cast-in-place Concrete and Reinforcement", "", ""),

    # A.31 External Works (extended)
    (re.compile(r"weighbridge|truck.*scale|weight.*bridge|yard.*weigh", re.I),
     "A.31", "External Site Works", "01", "External Site Works (incl. roads, levelling)"),

    # A.32 Builder's Work
    (re.compile(r"builder.?s.*work|cutting.*chase|hole.*forming|sleeve.*through|penetration.*through.*wall|opening.*through", re.I),
     "A.32", "Builders' Work in Connection with Services", "", ""),

    # Misc catch-all (H_Buildings etc.)
    (re.compile(r"^miscellaneous$|miscellaneous.*(?:item|work|sum)", re.I),
     "A.33", "Other Works", "", ""),

    # Main substation building (structural shell, M&E in B-book)
    (re.compile(r"main.*substation.*structural|substation.*(?:structural|building|architectural)", re.I),
     "A.04", "Cast-in-place Concrete and Reinforcement", "", ""),
]


# ── B-book keyword matching ──────────────────────────────
B_KEYWORDS = [
    # B.01 Mechanical Equipment
    (re.compile(r"pump(?!.*heat)(?!.*fire)|generator|compressor|engine|turbine|motor(?!.*electric.*small)|winch|hoist|crane.*mechanical", re.I),
     "B.01", "Mechanical Equipment Installation Works", "", ""),

    # B.03 Static Equipment
    (re.compile(r"tank|vessel|boiler|heat.*exchanger|pressure.*vessel|storage.*tank|fuel.*tank|water.*tank", re.I),
     "B.03", "Static Equipment and Process Metal Structures", "", ""),

    # B.04 Electrical
    (re.compile(r"electric|transformer|switch.?gear|switchboard|panel.*(electric|power|distribution|DB|MDB|SMDB)|circuit.*breaker|bus.?bar|cable(?!.*data)(?!.*network)(?!.*telecom)(?!.*fiber)(?!.*optic)|power.*(cable|supply|outlet|socket)|wiring|conduit.*(electric|power)|lighting.*(protection|arrester)|surge.*(protection|arrester)|earthing|grounding|lightning|generator.*(diesel|standby|backup)|UPS", re.I),
     "B.04", "Electrical Equipment Installation Works", "", ""),
    (re.compile(r"lighting(?!.*protection)(?!.*arrester)|light.*fixture|light.*fitting|luminaire|LED.*light|street.*light|flood.*light|emergency.*light|exit.*light", re.I),
     "B.04", "Electrical Equipment Installation Works", "06", "Lighting and Small Power"),

    # B.05 ELV / Intelligent Systems
    (re.compile(r"(CCTV|closed.?circuit|camera.*surveillance|video.*surveillance)|access.*control|intruder|burglar.*alarm|security.*system.*(alarm|detector)|PA.*system|public.*address|intercom|audio.*visual|AV.*system|BMS|building.*management.*system|SCADA|PLC|DDC.*control|smart.*building", re.I),
     "B.05", "Building Intelligent Systems (ELV)", "", ""),

    # B.07 HVAC
    (re.compile(r"HVAC|air.*condition|ventilation|air.*handling|AHU|FCU|VRF|VRV|chiller|cooling.*tower|condenser.*unit|split.*unit|duct.*work|air.*duct|exhaust.*fan|supply.*fan|ventilation.*fan|extract.*fan|fresh.*air", re.I),
     "B.07", "HVAC (Ventilation and Air Conditioning) Works", "", ""),

    # B.08 Pipework
    (re.compile(r"pipe(?!.*electric)(?!.*conduit)(?!.*cable)|pipeline|pipework|valve(?!.*gate.*complex)|flange|fitting.*pipe|sewage.*pipe|drainage.*pipe|water.*supply.*pipe|plumbing.*pipe", re.I),
     "B.08", "Industrial Pipework Works", "", ""),

    # B.09 Fire Protection
    (re.compile(r"fire.*(protection|detection|alarm|sprinkler|extinguish|hydrant|hose.*reel|blanket|rated.*door|damper|shutter)|sprinkler|fire.*pump|fire.*tank|smoke.*(detector|detection|alarm|control|extract)|FACP", re.I),
     "B.09", "Fire Protection Works", "", ""),

    # B.10 Plumbing
    (re.compile(r"plumbing|sanitary.*(system|installation)|water.*supply.*(system|installation)|cold.*water|hot.*water|solar.*water.*(heater|system)|drainage(?!.*(pavement|road|surface|storm|yard))|sewer|sewage|waste.*water|soak.?away|septic|grease.*trap", re.I),
     "B.10", "Plumbing, Heating and Gas Works", "", ""),

    # B.11 Telecom
    (re.compile(r"telecom|telephone|data.*(cable|cabling|network|outlet|socket)|structured.*cabling|fiber.*optic|fibre.*optic|network.*(cable|cabinet|rack|switch|patch.*panel)|RJ45|Cat.?[56]", re.I),
     "B.11", "Telecommunications Equipment and Cabling Works", "", ""),

    # B.12 Paint/Corrosion/Insulation (Installation context)
    (re.compile(r"painting.*(steel|metal|pipe|duct)|coating.*(steel|metal|pipe|duct)", re.I),
     "B.12", "Painting, Anti-corrosion and Thermal Insulation Works", "", ""),
]


# ── D-book keyword matching ──────────────────────────────
D_KEYWORDS = [
    # Anti-corrosion / coating (check before broad steel/pile patterns)
    (re.compile(r"anti.?corrosion|corrosion.*(protection|coating)|sacrificial.*anode|cathodic.*protection|rust.*proof", re.I),
     "D.08", "Steelwork", "", ""),

    # D.02 Dredging
    (re.compile(r"dredging|dredge|desilt|sediment.*removal|berth.*pocket|basin.*dredg|channel.*dredg|maintenance.*dredg|capital.*dredg", re.I),
     "D.02", "Dredging and Hydraulic Filling Works", "", ""),
    (re.compile(r"scour.*protection|armour.*layer|rip.?rap|rock.*armour|(?:200|300).?kg.*(?:rock|stone)|rock.*(?:protection|armour|blanket)|charting|hydrographic.*survey|bathymetric", re.I),
     "D.02", "Dredging and Hydraulic Filling Works", "", ""),

    # D.03 Navigation Aids
    (re.compile(r"navigation.*aid|buoy|beacon|lighthouse|light.*(tower|beacon)|navigational.*chart", re.I),
     "D.03", "Aids to Navigation Works", "", ""),

    # D.04 Earthworks (Marine)
    (re.compile(r"reclamation|reclaim|fill.*material.*marine|hydraulic.*fill|sand.*fill.*marine|drainage.*blanket|controlled.*fill|compaction.*(layer|ground)|compact.*ground.*(roller|vibrat)|vibrary.*roller|bulk.*fill.*material|surcharge.*(placement|material|removal)|removal.*surcharge", re.I),
     "D.04", "Earthworks (Marine)", "", ""),

    # D.05 Ground & Foundation
    (re.compile(r"ground.*(treatment|improvement).*marine|marine.*foundation|quay.*(foundation|base|bedding)|piling.*marine|marine.*pile|sheet.*pile.*(quay|marine|wharf)|king.*pile|instrumentation.*monitoring|liquefaction|sand.*(compaction|pile|drain|material)|PVD|prefabricated.*(vertical|drain)|wick.*drain|vertical.*drain|DCM|deep.*cement.*mix|settlement.*(case|treatment)", re.I),
     "D.05", "Ground and Foundation Works", "", ""),

    # D.06 Concrete Works (Marine)
    (re.compile(r"concrete.*(quay|wharf|jetty|pier|marine|dolphin|breasting|mooring)|quay.*(wall|deck|slab|beam)|wharf.*concrete|coping.*concrete|fender|bollard|marine.*concrete", re.I),
     "D.06", "Concrete Works", "", ""),

    # D.07 Reinforcement
    (re.compile(r"reinforcement.*(quay|wharf|marine)|rebar.*marine", re.I),
     "D.07", "Reinforcement Works", "", ""),

    # D.08 Steelwork
    (re.compile(r"steel.*(quay|wharf|jetty|pile|marine|dolphin)|marine.*steel|sheet.*pile.*steel|steel.*pipe.*pile|steel.*tube|bearing.*pile.*steel|anchor.*(pile|rod|tie)|tie.*rod|waling", re.I),
     "D.08", "Steelwork", "", ""),

    # D.09 Cargo Handling
    (re.compile(r"cargo.*handling|crane.*(rail|track|gantry|container|quay|ship.*to.*shore|STS)|container.*(handling|crane)", re.I),
     "D.09", "Cargo Handling Equipment Installation Works", "", ""),

    # D.10 Misc Marine
    (re.compile(r"fender.*marine|bollard.*marine|marine.*fender|marine.*bollard|mooring.*(dolphin|post|ring|hook)|breasting.*dolphin|rubbing.*strip|ladder.*marine", re.I),
     "D.10", "Miscellaneous Marine Works", "", ""),
]


def classify_item(item, vocab):
    """Classify a single BOQ item. Returns dict with classification fields."""
    desc = item['desc']
    l1 = item['l1']
    l3 = item['l3']
    unit = item['unit']

    result = {
        "discipline": "",
        "discipline_en": "",
        "category_code": "",
        "category_name": "",
        "category_name_en": "",
        "subcategory_code": "",
        "subcategory_name": "",
        "subcategory_name_en": "",
        "element": "",
        "element_en": "",
        "material": "",
        "spec": "",
        "source": "rule",  # rule / pattern / llm
    }

    # Step 1: Route by L1 section
    routing = SECTION_ROUTING.get(l1, ("FREE", "Unassigned"))
    discipline, discipline_en = routing

    result["discipline"] = discipline
    result["discipline_en"] = discipline_en

    # PRELIM items
    if discipline == "开办费":
        # All prelim items stay as PRELIM
        result["category_code"] = "PRELIM"
        result["category_name"] = "开办费"
        result["category_name_en"] = "Preliminaries"
        result["subcategory_code"] = ""
        result["subcategory_name"] = ""
        result["subcategory_name_en"] = ""
        result["source"] = "rule"
        return result

    if discipline == "FREE":
        result["source"] = "llm"
        return result

    # Step 1.5: Template/info rows (not real BOQ items)
    if re.match(r"please share applicable taxes|the tenderer shall separately list", desc, re.I):
        result["category_code"] = "INFO"
        result["category_name"] = "Info"
        result["category_name_en"] = "Instruction/Template"
        result["source"] = "rule"
        return result

    # Step 2: Check provisional sums
    prov_match = re.match(
        r'^Allow a provision for all other works and costs required for completion of the ["“](.+)[”"]\.?\s*$',
        desc, re.I
    )
    if prov_match:
        works_type = prov_match.group(1).upper().strip()
        if works_type in PROVISIONAL_SUMS:
            d, cat_code, cat_name, sub_code, sub_name = PROVISIONAL_SUMS[works_type]
            result["discipline"] = d
            result["discipline_en"] = "Civil & Decoration" if d == "A" else "General Installation"
            result["category_code"] = cat_code
            result["category_name_en"] = cat_name
            result["subcategory_code"] = sub_code
            result["subcategory_name_en"] = sub_name
            result["source"] = "provisional_sum"
            return result

    # Step 3: Check pattern rules (from classification_rules.json)
    for pattern, d, cat_code, cat_name, sub_code, sub_name in PATTERNS:
        if pattern.search(desc):
            result["discipline"] = d
            result["discipline_en"] = "Civil & Decoration" if d == "A" else "General Installation"
            result["category_code"] = cat_code
            result["category_name_en"] = cat_name
            result["subcategory_code"] = sub_code
            result["subcategory_name_en"] = sub_name
            result["source"] = "pattern"
            return result

    # Step 3.5: Check L2 section mapping
    l2_key = item.get('l2', '')
    # Try exact match first, then partial match
    l2_map_entry = L2_CATEGORY_MAP.get(l2_key)
    if l2_map_entry is None:
        # Try partial match
        for key, val in L2_CATEGORY_MAP.items():
            if key.split('\n')[0].strip() == l2_key.split('\n')[0].strip():
                l2_map_entry = val
                break
    if l2_map_entry:
        cat_code, cat_name, sub_code, sub_name = l2_map_entry
        result["category_code"] = cat_code
        result["category_name_en"] = cat_name
        result["subcategory_code"] = sub_code
        result["subcategory_name_en"] = sub_name
        result["source"] = "l2_map"
        return result

    # Step 4: Keyword matching based on Discipline
    if discipline == "A":
        keywords = A_KEYWORDS
    elif discipline == "B":
        keywords = B_KEYWORDS
    elif discipline == "D":
        keywords = D_KEYWORDS
    else:
        keywords = A_KEYWORDS  # default

    for pattern, cat_code, cat_name, sub_code, sub_name in keywords:
        if pattern.search(desc):
            result["category_code"] = cat_code
            result["category_name_en"] = cat_name
            result["subcategory_code"] = sub_code
            result["subcategory_name_en"] = sub_name
            result["source"] = "keyword"
            return result

    # Step 5: Cross-check for D-section items against A-book keywords
    # (many marine projects have civil-type works like ground treatment, concrete)
    if discipline == "D":
        for pattern, cat_code, cat_name, sub_code, sub_name in A_KEYWORDS:
            # Skip A-book-only categories that don't apply to marine
            if cat_code in ("A.13", "A.14", "A.20", "A.21", "A.22", "A.23", "A.24",
                            "A.08", "A.12", "A.32", "A.33"):
                continue
            if pattern.search(desc):
                result["category_code"] = cat_code
                result["category_name_en"] = cat_name
                result["subcategory_code"] = sub_code
                result["subcategory_name_en"] = sub_name
                result["source"] = "keyword_xD"
                return result

    # Step 6: Cross-check for B-section items against A-book keywords
    # (builder's work, civil supports for MEP)
    if discipline == "B":
        for pattern, cat_code, cat_name, sub_code, sub_name in A_KEYWORDS:
            if cat_code not in ("A.32", "A.12"):
                continue
            if pattern.search(desc):
                result["category_code"] = cat_code
                result["category_name_en"] = cat_name
                result["subcategory_code"] = sub_code
                result["subcategory_name_en"] = sub_name
                result["source"] = "keyword_xB"
                return result

    # Step 7: No match → LLM fallback
    result["source"] = "llm"
    return result


def _finalize_item(item):
    """Compute SortKey and split Civil & Decoration Discipline."""
    cat_code = item.get("category_code", "")
    disc_en = item.get("discipline_en", "")

    # SortKey = category_code (division code); PRELIM stays PRELIM
    if cat_code == "PRELIM":
        item["sortkey"] = "PRELIM"
    else:
        item["sortkey"] = cat_code

    # Split Civil & Decoration → Civil / Decoration based on division number
    if disc_en == "Civil & Decoration" and cat_code.startswith("A."):
        try:
            div_num = int(cat_code.split(".")[1])
            item["discipline_en"] = "Decoration" if 20 <= div_num <= 29 else "Civil"
        except (IndexError, ValueError):
            pass


def classify_all(items, vocab):
    """Classify all items. Returns (classified, unmatched_for_llm)."""
    classified = []
    unmatched = []

    for item in items:
        result = classify_item(item, vocab)
        item.update(result)
        _finalize_item(item)
        classified.append(item)
        if result["source"] == "llm":
            unmatched.append(item)

    return classified, unmatched


def write_to_excel(classified_items, template_path, output_path, sheet=None):
    """Write classification results back into the 报价工作台 layout."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Border, Side
    import layout

    wb = openpyxl.load_workbook(template_path)
    ws = layout.get_sheet(wb, sheet)

    cols = layout.require(layout.find_columns(ws), layout.AI_COLS)
    col_disc = cols["Discipline"]
    col_sortkey = cols["SortKey"]
    col_cat = cols["Category"]
    col_subcat = cols["Subcategory"]
    col_elem = cols["Element"]

    FILL_YELLOW = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
    FONT_DATA = Font(name="Microsoft YaHei UI", size=9)
    THIN_BORDER = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    written = 0
    for item in classified_items:
        row = item['excel_row']

        # Discipline
        if item.get('discipline_en'):
            ws.cell(row=row, column=col_disc, value=item['discipline_en'])

        # SortKey (division code, yellow fill like other AI columns)
        sk = item.get('sortkey', '')
        if sk:
            sk_cell = ws.cell(row=row, column=col_sortkey, value=sk)
            sk_cell.fill = FILL_YELLOW
            sk_cell.font = FONT_DATA
            sk_cell.border = THIN_BORDER

        # Category
        if item.get('category_name_en'):
            ws.cell(row=row, column=col_cat, value=item['category_name_en'])

        # Subcategory  (use code_name format or just name)
        subcat_val = ""
        if item.get('subcategory_code') and item.get('subcategory_name_en'):
            subcat_val = f"{item['subcategory_code']} {item['subcategory_name_en']}"
        elif item.get('subcategory_name_en'):
            subcat_val = item['subcategory_name_en']
        if subcat_val:
            ws.cell(row=row, column=col_subcat, value=subcat_val)

        # Element
        if item.get('element_en'):
            ws.cell(row=row, column=col_elem, value=item['element_en'])

        written += 1

    wb.save(output_path)
    return written


if __name__ == "__main__":
    print("Loading norms vocabulary...")
    vocab = load_vocab()
    for book in "ABCDE":
        nd = len(vocab[book]["divisions"])
        ns = sum(len(s) for s in vocab[book]["sub_divisions"].values())
        ni = len(vocab[book]["items"])
        print(f"  Book {book}: {nd} divisions, {ns} sub-divisions, {ni} enterprise items")

    print("\nClassification engine ready.")
    print("Run via the main pipeline script.")
