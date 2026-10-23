# Category dataset: labelling guide

Task **T-10** (US-26 AI Category Suggestion). This guide defines how every expense description in the category dataset is labelled. The category model (T-22) is trained and evaluated on these labels, so a second person must be able to apply the guide and get the same answers.

## Files

| File | Rows | Use |
|---|---|---|
| `ml/data/categories_train.csv` | 1,200 (100 per category) | Training the category model |
| `evals/categories/heldout.csv` | 300 (25 per category) | **Frozen** test set: never used for training or tuning, never edited after the agreement check |

Both files have the columns `id,description,category`. IDs are `TR-0001…` (train) and `HO-0001…` (held out). Every `category` value is exactly one of the 12 names below.

## The 12 categories

These are the 12 default categories from the product document; the spelling must match exactly.

| Category | Use it for | Examples |
|---|---|---|
| **Food & Dining** | Prepared food and drink: restaurants, cafés, food delivery, canteen, mess, tiffin, street food, chai, snacks | swiggy order, zomato biryani, canteen maggi, chai sutta, mess bill, tiffin service |
| **Groceries** | Food and household supplies to cook or use at home: supermarkets, quick-commerce apps, kirana, vegetables, milk | dmart monthly, blinkit milk bread, swiggy instamart, sabzi, doodh, atta |
| **Travel & Transport** | Getting around and trips: cabs, autos, metro, trains, buses, flights, fuel, tolls, parking, vehicle service, hotels on a trip | uber auto, metro card recharge, irctc ticket, petrol, fastag recharge, oyo room |
| **Shopping** | Things bought to own: clothes, shoes, electronics, gadgets, home items, general online orders | amazon earphones, myntra jeans, decathlon shoes, pressure cooker, croma |
| **Bills & Utilities** | Recurring household services: electricity, water, gas, mobile recharge, broadband, DTH | electricity bill, jio recharge, wifi bill, tata play recharge, lpg cylinder |
| **Rent & Housing** | Living space and keeping it running: rent, PG, hostel room, maintenance, deposit, brokerage, repairs, house help, movers | pg rent, society maintenance, plumber, maid salary, packers and movers |
| **Entertainment** | Fun and leisure: streaming, movies, concerts, games, events, outings, books read for fun | netflix, bookmyshow, pvr, bgmi uc, wonderla, kindle novel |
| **Health** | Body and medical care: medicines, doctors, labs, hospitals, dentist, eye care, gym, health insurance, supplements | apollo pharmacy, doctor fees, blood test, lenskart glasses, gym membership |
| **Education** | Learning: fees, coaching, courses, textbooks, stationery, printouts, exam registrations | semester fees, udemy course, xerox, notebooks, gate registration |
| **Personal Care** | Grooming and looking after clothes: salon, parlour, toiletries, cosmetics, laundry, tailoring | haircut, nykaa order, shampoo, dhobi, dry cleaning, alteration |
| **Gifts & Donations** | Money spent on someone else as a gift, or given away | birthday gift, shagun, temple donation, rakhi gift, gift card, flowers for mom |
| **Other** | Anything that fits none of the above: courier, government and bank fees, fines, pets, legal papers, unclear "misc" entries | dtdc courier, passport fee, atm fee, traffic challan, dog food, stamp paper |

## Rules for tricky cases

Apply these in order; the first rule that matches decides the label.

1. **Same app, different service: label the service, not the app.**
   - Swiggy / Zomato (food delivery) → Food & Dining; **Swiggy Instamart** → Groceries.
   - Urban Company **salon/spa** → Personal Care; Urban Company **cleaning / pest control** → Rent & Housing.
   - Amazon / Flipkart orders → Shopping; **Amazon Prime membership** → Entertainment; **Amazon gift card** → Gifts & Donations.
2. **Ready-to-eat vs. to cook.** Prepared food and drinks (including bakery items, juice, ice cream) → Food & Dining. Ingredients and home supplies (milk, eggs, bread, vegetables, meat from a butcher) → Groceries.
3. **Subscriptions follow what they are for.** OTT and music (Netflix, Hotstar, Spotify) → Entertainment. Phone, internet and DTH → Bills & Utilities. Newspaper or magazine → Other.
4. **Gym and fitness → Health** (not Personal Care). Glasses and contact lenses → Health. Health insurance → Health.
5. **Cosmetics and toiletries → Personal Care**, including Nykaa, Purplle and Mamaearth orders.
6. **Books.** Textbooks, reference books and study material → Education. Novels, comics and audiobooks → Entertainment.
7. **Hostel.** Hostel *room rent/charges* → Rent & Housing. Hostel *canteen or mess food* → Food & Dining. Tuition or college fees → Education.
8. **Trips.** Hotels and travel bookings during a trip → Travel & Transport (not Rent & Housing).
9. **Vehicles.** Fuel, tolls, parking, servicing, puncture repair, car wash → Travel & Transport.
10. **Gifts.** Anything bought *for someone else as a gift* → Gifts & Donations, even if the item itself (clothes, flowers) would otherwise be Shopping. Things bought for yourself or your home → their normal category.
11. **Pets → Other** (food, litter, vet). Health is for people.
12. **Not enough information.** If the description gives no clue ("misc", "random expense", "cash expense") → Other.
13. **Amounts, dates and payment words never decide the label.** "paid", "upi/", "Rs 250", "rs.250", "inr 250", "250/-" and casing are ignored.

## How the data was built

- **Wording:** descriptions are written the way people type expense notes and UPI remarks in India: merchant names, short notes, Hinglish (*doodh*, *kirana*, *dawai*, *chai sutta*), common typos (*swigy*, *zomoto*), amounts in several formats (`Rs 250`, `rs.250`, `inr 250`, `250/-`; plain ASCII so the files open correctly in Excel), and prefixes such as `paid` and `upi/`.
- **Balance:** exactly 125 rows per category (100 train + 25 held out), so macro-F1 is not dominated by common categories.
- **No duplicates:** two descriptions that differ only in spacing, punctuation or casing count as duplicates and are removed.
- **Honest split:** each held-out row comes from a core phrase that never appears in training (for example, *swigy order* may be held out while *swiggy order* is in training). The test therefore measures new wordings of known kinds of spending, not memorised strings.
- **Targets** (from the product document, measured on the held-out file): macro-F1 ≥ 0.85, top-3 accuracy ≥ 0.95.

## Agreement check (done-when for T-10)

A second labeller must agree with these labels on **at least 90% of a 100-row sample** before the data is used.

1. Take 100 random rows from `categories_train.csv` and give the second labeller **only the `id` and `description` columns**, plus this guide.
2. They label each row independently, without seeing the existing labels.
3. Agreement = rows where both labels match ÷ 100.
4. If agreement is below 90%, read the disagreements, make the matching rule above clearer, relabel the affected rows and repeat with a fresh sample.

**Result** (fill in after the check):

| Item | Value |
|---|---|
| Second labeller | _to be filled_ |
| Date | _to be filled_ |
| Sample | 100 rows from `categories_train.csv` |
| Rows in agreement | _to be filled_ / 100 |
| Rules clarified after the check | _none yet_ |

## Changing the data

- `evals/categories/heldout.csv` is frozen once the agreement check passes. Do not edit, add or remove rows; a new test set would need a new file and a note in `ml/MODELS.md`.
- New training rows (for example, real expense notes collected from the team or the survey) can be added to `categories_train.csv` if they follow this guide and keep the categories roughly balanced.
