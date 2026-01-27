# Item Table Migration - Simple 3-Step Process

This guide will update your item table to match the target schema exactly.

## Quick Overview

1. **Step 1**: Add `item_code` column (nullable)
2. **Step 2**: Populate `item_code` with your values
3. **Step 3**: Complete migration (add other columns, constraints, indexes)

## Step-by-Step Instructions

### 📋 Step 1: Add item_code Column

Run this command:

```bash
psql -d your_database -f migrations/step1_add_item_code_column.sql
```

This adds the `item_code` column to your table (as nullable initially).

---

### ✏️ Step 2: Populate item_code Values

**You must choose how to populate item_code.** Open `step2_populate_item_code_examples.sql` and choose a strategy:

#### Option A: Use existing SKU codes
```sql
UPDATE item SET item_code = sku_code WHERE item_code IS NULL;
```

#### Option B: Generate with prefix
```sql
UPDATE item SET item_code = 'ITM-' || LPAD(item_id::text, 6, '0') WHERE item_code IS NULL;
```

#### Option C: Manual entry
```sql
UPDATE item SET item_code = 'WATER-500ML' WHERE item_id = 1;
UPDATE item SET item_code = 'BLANKET-STD' WHERE item_id = 2;
-- ... etc
```

**Then verify:**
```sql
-- All should be populated (returns 0)
SELECT COUNT(*) FROM item WHERE item_code IS NULL;

-- No duplicates (returns no rows)
SELECT item_code, COUNT(*) FROM item GROUP BY item_code HAVING COUNT(*) > 1;
```

---

### ✅ Step 3: Complete the Migration

After item_code is populated, run:

```bash
psql -d your_database -f migrations/step3_complete_migration.sql
```

This will:
- Add all missing columns (units_size_vary_flag, is_batched_flag, can_expire_flag, issuance_order)
- Make item_code NOT NULL
- Add all constraints and indexes
- Remove obsolete columns (category_code, expiration_apply_flag)

---

## What Gets Changed?

### ✅ Columns Added
- `item_code` - VARCHAR(16), unique, uppercase
- `units_size_vary_flag` - BOOLEAN, default FALSE
- `is_batched_flag` - BOOLEAN, default TRUE
- `can_expire_flag` - BOOLEAN, default FALSE
- `issuance_order` - VARCHAR(20), default 'FIFO'

### ❌ Columns Removed
- `category_code` (replaced by category_id FK)
- `expiration_apply_flag` (replaced by can_expire_flag)

### 🔧 Columns Modified
- `category_id` - Changed to NOT NULL

### 📊 Indexes Created
- `dk_item_1` on `item_desc`
- `dk_item_2` on `category_id`
- `dk_item_3` on `sku_code`

---

## Safety Features

- ✅ All scripts use transactions (auto-rollback on error)
- ✅ Step 3 validates item_code before proceeding
- ✅ No data loss - existing data is preserved
- ✅ Clear error messages if validation fails

---

## Troubleshooting

### Error: "item_code has NULL values"
**Solution**: Go back to Step 2 and populate all item_code values

### Error: "Duplicate item_code values found"
**Solution**: Ensure each item has a unique item_code
```sql
SELECT item_code, COUNT(*) FROM item GROUP BY item_code HAVING COUNT(*) > 1;
```

### Error: "category_id has NULL values"
**Solution**: Populate category_id first
```sql
UPDATE item SET category_id = <valid_id> WHERE category_id IS NULL;
```

---

## After Migration

Your item table will exactly match the target schema with:
- All required columns
- All constraints properly named
- All indexes in place
- No data lost

Run this to verify:
```sql
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'item' 
ORDER BY ordinal_position;
```
