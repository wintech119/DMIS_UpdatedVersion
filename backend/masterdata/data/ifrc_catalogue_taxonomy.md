# IFRC/ICRC Standard Products Catalogue - Taxonomy Reference
# Version: 2024 (real IFRC 15-character codification)
#
# FORMAT (do not change heading levels):
#   ## GROUP:<G>   <Label>       1-letter Group (18 official groups)
#   ### FAMILY:<FAM> <Label>     3-letter Family code
#   #### CATEGORY:<CAT> <Label>  4-letter Category code
#   - ITEM: <description>        representative items (keyword source)
#   - ITEM: <description> | KEY=VALUE | ...    optional governed metadata
#
# Supported item metadata keys:
#   IFRC_CODE, SIZE_WEIGHT, FORM, MATERIAL, SPEC_SEGMENT
#
# CODE STRUCTURE:
#   GROUP(1) + FAMILY(3) + CATEGORY(4) + SPEC(1-7) + SEQ(2) = max 17 chars
#   MDRECOMPA1001 = M(Medical)+DRE(Dressings)+COMP(Compress)+A10+seq01
#   HSHTRPLPE01   = H(Housing)+SHE(Shelter)+TRPL(Tarpaulin)+PE+seq01

---

## GROUP:A Administration

### FAMILY:OFC Office Supplies and Stationery

#### CATEGORY:PAPE Paper and Notebooks
- ITEM: Paper, office, A4
- ITEM: Notebook, ruled
- ITEM: Notepad

#### CATEGORY:PENC Pens, Pencils and Markers
- ITEM: Pen, ballpoint
- ITEM: Pencil, standard
- ITEM: Marker, permanent
- ITEM: Stationery kit

---

## GROUP:C Radio and Telecommunications

### FAMILY:RAD Radio Equipment

#### CATEGORY:HAND Handheld Radios
- ITEM: Radio, VHF handheld
- ITEM: Radio, UHF handheld
- ITEM: Walkie-talkie
- ITEM: Two-way radio

#### CATEGORY:BSTN HF Base Station Radios
- ITEM: Radio, HF transceiver
- ITEM: HF transceiver

### FAMILY:COM Communications Equipment

#### CATEGORY:SATP Satellite Phones
- ITEM: Satellite phone, Thuraya
- ITEM: Satellite phone, Iridium
- ITEM: Satphone

#### CATEGORY:SATT Satellite Terminals
- ITEM: Satellite communication terminal
- ITEM: VSAT terminal
- ITEM: Wireless bridge

---

## GROUP:D Drugs

### FAMILY:ANL Analgesics and Anti-Inflammatory

#### CATEGORY:PARA Paracetamol
- ITEM: Paracetamol tablet, 500 mg
- ITEM: Acetaminophen tablet
- ITEM: Panadol
- ITEM: Paracetamol suppository

#### CATEGORY:IBUP Ibuprofen
- ITEM: Ibuprofen tablet, 400 mg
- ITEM: Brufen tablet
- ITEM: Anti-inflammatory tablet

### FAMILY:ANB Antibiotics

#### CATEGORY:AMOX Amoxicillin and Penicillins
- ITEM: Amoxicillin tablet, 250 mg | SIZE_WEIGHT=250 MG | FORM=TABLET
- ITEM: Amoxicillin tablet, 500 mg | SIZE_WEIGHT=500 MG | FORM=TABLET
- ITEM: Amoxicillin clavulanic acid tablet
- ITEM: Ampicillin injection
- ITEM: Penicillin tablet

#### CATEGORY:AZIT Other Antibiotics
- ITEM: Azithromycin tablet, 500 mg
- ITEM: Ciprofloxacin tablet, 500 mg
- ITEM: Cotrimoxazole tablet
- ITEM: Doxycycline tablet
- ITEM: Metronidazole tablet
- ITEM: Ceftriaxone injection

### FAMILY:ANT Antiparasitics

#### CATEGORY:COAR Antimalarials
- ITEM: Artemether lumefantrine tablet
- ITEM: Coartem tablet
- ITEM: Antimalarial tablet
- ITEM: Chloroquine tablet

#### CATEGORY:RDTE Rapid Diagnostic Tests
- ITEM: Malaria rapid diagnostic test
- ITEM: Malaria RDT
- ITEM: HIV rapid test
- ITEM: Pregnancy test
- ITEM: Urine test strips

### FAMILY:ORS Oral Rehydration

#### CATEGORY:ORSA ORS Sachets
- ITEM: Oral rehydration salts, sachet
- ITEM: ORS sachet
- ITEM: Rehydration salt sachet
- ITEM: Electrolyte solution sachet

### FAMILY:VIT Vitamins and Supplements

#### CATEGORY:VITA Vitamins
- ITEM: Vitamin A capsule
- ITEM: Multivitamin tablet
- ITEM: Zinc sulfate tablet

---

## GROUP:E Engineering

### FAMILY:GEN Generators and Power Systems

#### CATEGORY:PORT Portable Generators
- ITEM: Generator, petrol, 2 kVA
- ITEM: Generator, diesel, 5 kVA
- ITEM: Generator, diesel, 10 kVA
- ITEM: Generator, diesel, 20 kVA
- ITEM: Portable generator

#### CATEGORY:SOLA Solar Power Systems
- ITEM: Solar panel kit, 50 W
- ITEM: Solar panel kit, 100 W
- ITEM: Solar system, photovoltaic
- ITEM: Solar kit

### FAMILY:LGT Lighting Equipment

#### CATEGORY:SLRL Solar Lanterns and Lamps
- ITEM: Solar lantern
- ITEM: Solar lamp
- ITEM: Rechargeable lantern
- ITEM: LED lamp, portable

#### CATEGORY:TRCL Torches and Headlamps
- ITEM: Torch, LED
- ITEM: Flashlight, LED
- ITEM: Headlamp
- ITEM: Headtorch

### FAMILY:BAT Batteries and Electrical Accessories

#### CATEGORY:ALKA Alkaline Batteries
- ITEM: Battery, alkaline AA
- ITEM: Battery, alkaline D cell
- ITEM: Batteries, alkaline
- ITEM: Battery deep-cycle 12V

#### CATEGORY:ELEC Electrical Accessories
- ITEM: Cable, electrical extension
- ITEM: Power inverter
- ITEM: Voltage stabiliser
- ITEM: Air conditioning unit
- ITEM: Air conditioner

### FAMILY:FUE Fuel and Lubricants

#### CATEGORY:DIES Diesel, Petrol and Kerosene
- ITEM: Fuel, diesel, per drum
- ITEM: Fuel, petrol, per drum
- ITEM: Diesel fuel
- ITEM: Petrol fuel
- ITEM: Kerosene
- ITEM: Lubricant, engine oil

---

## GROUP:F Food

### FAMILY:CAN Canned Food

#### CATEGORY:MEAT Canned Meat
- ITEM: Corned beef, canned
- ITEM: Corned beef, canned, 200 g | IFRC_CODE=FCANMEATCB200G | SIZE_WEIGHT=200 G | FORM=CANNED
- ITEM: Corned beef, canned, 500 g | IFRC_CODE=FCANMEATCB500G | SIZE_WEIGHT=500 G | FORM=CANNED
- ITEM: Canned meat, generic
- ITEM: Luncheon meat, canned

#### CATEGORY:FISH Canned Fish
- ITEM: Tuna, canned
- ITEM: Sardines, canned
- ITEM: Mackerel, canned
- ITEM: Herrings, canned
- ITEM: Tinned fish

#### CATEGORY:BEAN Canned Beans and Legumes
- ITEM: Baked beans, canned
- ITEM: Kidney beans, canned
- ITEM: Canned peas

### FAMILY:CER Cereals and Grains

#### CATEGORY:RICE Rice
- ITEM: Rice, white, parboiled
- ITEM: Rice, long grain

#### CATEGORY:MAIZ Maize and Cornmeal
- ITEM: Maize flour
- ITEM: Cornmeal
- ITEM: Grits
- ITEM: Cereal, maize

#### CATEGORY:FLOU Wheat Flour
- ITEM: Wheat flour, all-purpose
- ITEM: Flour
- ITEM: Cereal, wheat flour

#### CATEGORY:OATS Oats
- ITEM: Oats, rolled
- ITEM: Oatmeal
- ITEM: Porridge oats

### FAMILY:OIL Oils and Fats

#### CATEGORY:COOK Cooking Oil
- ITEM: Cooking oil, vegetable, 5 L
- ITEM: Palm oil
- ITEM: Canola oil
- ITEM: Sunflower oil

### FAMILY:SUG Sugar

#### CATEGORY:SUGR Granulated Sugar
- ITEM: Sugar, granulated, white

### FAMILY:SAL Salt

#### CATEGORY:SALT Iodized Salt
- ITEM: Salt, iodized, 1 kg
- ITEM: Table salt

### FAMILY:NUT Nutritional Products

#### CATEGORY:BSCT Energy Biscuits
- ITEM: Biscuit, high-energy, fortified
- ITEM: Energy biscuit
- ITEM: High-energy biscuit

#### CATEGORY:RUTF Therapeutic Food
- ITEM: Ready-to-use therapeutic food, RUTF
- ITEM: Plumpy-Nut

### FAMILY:PLS Pulses and Dried Legumes

#### CATEGORY:LENT Lentils and Dried Beans
- ITEM: Lentils, red, dried
- ITEM: Split peas, dried
- ITEM: Beans, dried
- ITEM: Pulses, mixed

---

## GROUP:H Housing, shelter

### FAMILY:SHE Shelter Materials

#### CATEGORY:TRPL Tarpaulins and Plastic Sheeting
- ITEM: Tarpaulin, polyethylene, 4x5 m
- ITEM: Tarpaulin, 4x6 m
- ITEM: Tarpaulin, 8x10 m
- ITEM: Plastic sheeting, polyethylene
- ITEM: Poly sheeting, heavy duty

#### CATEGORY:TENT Tents
- ITEM: Family tent, 16 m2
- ITEM: Family tent, 24 m2
- ITEM: Emergency shelter tent
- ITEM: Tent accessories kit

#### CATEGORY:ROPE Rope and Cord
- ITEM: Rope, nylon, 10 mm
- ITEM: Rope, polyethylene, 6 mm
- ITEM: Guy rope
- ITEM: Fixings kit, stakes and pegs

### FAMILY:BED Bedding and Sleeping

#### CATEGORY:BLAN Blankets
- ITEM: Blanket, synthetic, medium thermal
- ITEM: Blanket, cotton
- ITEM: Blanket, wool
- ITEM: Fleece blanket
- ITEM: Emergency blanket, thermal

#### CATEGORY:SLPB Sleeping Bags
- ITEM: Sleeping bag, lightweight
- ITEM: Sleeping bag, heavy thermal
- ITEM: Sleep bag, adult

#### CATEGORY:MTRS Mattresses
- ITEM: Mattress, foam
- ITEM: Pillow

### FAMILY:KIT Household Kits

#### CATEGORY:HHKT Non-Food Item Kits
- ITEM: Household kit, non-food items
- ITEM: NFI kit, family
- ITEM: Family kit, basic

#### CATEGORY:KTKN Kitchen and Cooking Kits
- ITEM: Kitchen kit, cooking set
- ITEM: Cooking pot, aluminium, 5 L
- ITEM: Cooking pot, aluminium, 10 L
- ITEM: Cooking set, family
- ITEM: Plate, plastic
- ITEM: Utensils set
- ITEM: Stove, kerosene

---

## GROUP:K Kits, Modules and Sets

### FAMILY:FAK First Aid Kits

#### CATEGORY:BASK Basic First Aid Kits
- ITEM: First aid kit, basic
- ITEM: First aid kit, vehicle
- ITEM: FAK, delegate
- ITEM: Trauma kit, first responder

### FAMILY:HYK Hygiene Kits

#### CATEGORY:STND Standard Hygiene and Dignity Kits
- ITEM: Hygiene kit, family
- ITEM: Dignity kit
- ITEM: Hygiene pack, standard

### FAMILY:MED Medical Kits

#### CATEGORY:EMRG Emergency Health Kits
- ITEM: Emergency health kit, interagency
- ITEM: Medical kit, rapid deployment
- ITEM: Hospital emergency surgery kit

#### CATEGORY:CHOL Cholera Kits
- ITEM: Cholera kit, beds and rehydration sets
- ITEM: Cholera kit, disinfection

---

## GROUP:M Medical Renewable Items

### FAMILY:DRE Dressings and Wound Care

#### CATEGORY:COMP Compresses and Wound Pads
- ITEM: Compress, aluminized, 10x10 cm, sterile
- ITEM: Compress, aluminized, 20x20 cm, sterile
- ITEM: Wound pad, sterile
- ITEM: Dressing pad, sterile

#### CATEGORY:BAND Bandages
- ITEM: Bandage, crepe, elastic, 10 cm
- ITEM: Bandage, roller, 15 cm
- ITEM: Elastic bandage
- ITEM: Triangular bandage

#### CATEGORY:GAZE Gauze
- ITEM: Gauze swab, sterile, 10x10 cm
- ITEM: Gauze roll, 10 cm x 5 m
- ITEM: Gauze dressing

#### CATEGORY:SUTR Sutures
- ITEM: Suture, absorbable, chromic catgut
- ITEM: Suture, non-absorbable, nylon
- ITEM: Surgical suture set

### FAMILY:SYR Syringes and Needles

#### CATEGORY:DISP Disposable Syringes
- ITEM: Syringe, disposable, 2 ml
- ITEM: Syringe, disposable, 5 ml
- ITEM: Syringe, auto-disable
- ITEM: Needle, hypodermic
- ITEM: IV giving set
- ITEM: IV cannula

### FAMILY:GLV Gloves

#### CATEGORY:LATX Latex and Examination Gloves
- ITEM: Gloves, examination, latex, small
- ITEM: Gloves, examination, latex, medium
- ITEM: Gloves, examination, latex, large
- ITEM: Gloves, surgical, sterile
- ITEM: Gloves, nitrile, examination

### FAMILY:MAS Masks and Protective Equipment

#### CATEGORY:SURG Surgical Masks
- ITEM: Mask, surgical, disposable
- ITEM: Face mask, medical grade
- ITEM: Mask, N95 respirator
- ITEM: Gown, surgical, disposable

### FAMILY:COL Cold Chain

#### CATEGORY:COLD Cold Boxes and Vaccine Carriers
- ITEM: Cold box, vaccine carrier, 4 L
- ITEM: Cold box, 20 L
- ITEM: Ice packs
- ITEM: Vaccine carrier, insulated
- ITEM: Data-logger thermometer

---

## GROUP:T Transport

### FAMILY:VEH Vehicles

#### CATEGORY:TRCK Trucks and 4WD Vehicles
- ITEM: Truck, 4x4 double-cab
- ITEM: Pickup truck, 4-wheel drive
- ITEM: Car, 4x4
- ITEM: Vehicle, sedan

#### CATEGORY:BIKE Motorcycles
- ITEM: Motorcycle, 125 cc
- ITEM: Motorbike
- ITEM: Bicycle

#### CATEGORY:VKIT Vehicle Kits
- ITEM: Vehicle kit, spare parts
- ITEM: Vehicle kit, recovery

---

## GROUP:W Water and Sanitation

### FAMILY:WTR Water Treatment, Storage and Distribution

#### CATEGORY:DRWT Drinking Water and Storage
- ITEM: Bottled water, drinking, 1.5 L
- ITEM: Water tank, flexible bladder, 5000 L
- ITEM: Water tank, rigid, 1000 L
- ITEM: Potable water container

#### CATEGORY:TABL Water Purification Tablets
- ITEM: Water purification tablet, aquatab | FORM=TABLET | MATERIAL=CHLORINE
- ITEM: Sodium dichloroisocyanurate tablet
- ITEM: Chlorine tablet, water treatment
- ITEM: Aquatab

#### CATEGORY:CHLR Chlorine Treatment
- ITEM: Chlorine granules, water treatment
- ITEM: Sodium hypochlorite solution
- ITEM: Water treatment chemical

#### CATEGORY:CONT Water Containers and Jerrycans
- ITEM: Jerrycan, plastic, 10 L
- ITEM: Jerrycan, plastic, 20 L
- ITEM: Water jug, collapsible
- ITEM: Water container
- ITEM: Jerry can

#### CATEGORY:FLTR Water Filters
- ITEM: Water filter, household, ceramic
- ITEM: Biosand filter
- ITEM: Household water filter

#### CATEGORY:PUMP Water Pumps and Infrastructure
- ITEM: Pump, water, motorised
- ITEM: Hand pump, water
- ITEM: Pump, submersible
- ITEM: Hose, water, 25 m
- ITEM: Tap stand
- ITEM: Water-testing kit, field

### FAMILY:HYG Hygiene Products

#### CATEGORY:SOAP Soap
- ITEM: Soap, bar, laundry
- ITEM: Soap, bar, toilet
- ITEM: Soap, liquid
- ITEM: Bar soap

#### CATEGORY:SANR Hand Sanitiser
- ITEM: Hand sanitiser, 500 ml
- ITEM: Hand sanitizer, alcohol gel
- ITEM: Alcohol rub

#### CATEGORY:TOIL Toilet Paper
- ITEM: Toilet paper, roll
- ITEM: Toilet tissue

#### CATEGORY:BUCK Buckets and Pails
- ITEM: Bucket, plastic, 10 L
- ITEM: Bucket, collapsible, 10 L
- ITEM: Pail, plastic

#### CATEGORY:DPKM Menstrual Hygiene Kits
- ITEM: Menstrual hygiene kit, disposable pads
- ITEM: Menstrual hygiene kit, reusable pads
- ITEM: Sanitary pad, disposable
- ITEM: Dignity kit, women

### FAMILY:SAN Sanitation

#### CATEGORY:LATR Latrines and Sanitation
- ITEM: Latrine slab, concrete
- ITEM: Latrine pit kit
- ITEM: Portable toilet
- ITEM: Excreta-disposal kit
- ITEM: Sanitation kit
