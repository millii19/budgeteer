# Budgeteer

A tool to collect and keep track of expenses and invoices. Made for my volleyball club.

## Quick Start

1. Create the virtual environment and install dependencies:

```bash
uv sync
```

2. Create your runtime config file:

```bash
mkdir -p ~/.config/budgeteer
cp config.example.yaml ~/.config/budgeteer/config.yaml
```

3. Run the interactive recorder:

```bash
uv run budgeteer record-expense
```

4. Run via uvx from this project:

```bash
uvx --from . budgeteer record-expense
```

## Recording an expense
Interactive cli tool that records an expense and generates a useful transaction code to be appended to the bank transaction
 - Interactive screen to enter the required fields:
   - datetime of transaction: default current timestamp in YYYY-MM-DDTHH:MM:SS format
   - name of recipient: store past recipients and offer autocomplete, sort by last time used and filter by entered characters
   - IBAN: confirm the recipients IBAN if selected from the list or enter it if it's a new recipient
   - amount: accepts both , and . as comma
   - category and subcategories: depending on configured hierarchical categories, chained dropdown using arrow keys for selection
   - comment: empty by default, not required
 - will append the expense to a sqlite file

## Viewing Expense History
You can also view the past recorded expenses sorted by record-time. From there you can delete or edit a record.

```bash
uv run budgeteer history
```

## Exporting Expenses
You can export expenses from the last 24 hours to CSV. Sensitive banking details (IBAN) are not included.

```bash
uv run budgeteer export-last-24h
```

Optional output path:

```bash
uv run budgeteer export-last-24h --output /tmp/last24h.csv
```


## Configuration
There is a config file, you can copy and adapt the default-template.

- Project setup is in `pyproject.toml`.
- Runtime app configuration is YAML (see `config.example.yaml`).

### Localisation
Only applies to CLI tool text.
- DE
- EN 

### Currency
- Euro (€)

### Categories and Subcategories
Hierarchical chain of catagories.


## Todo:
 - Don't allow saving same transaction code -> warning
 - when updating a transaction I want the transaction code also to be regenerated
 - as website with file upload and forms integration?