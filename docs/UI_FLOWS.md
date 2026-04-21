# Greenlight UI Flow Map

Complete state diagram of every screen and transition in the Greenlight application.

## Main Flow

```mermaid
stateDiagram-v2
    [*] --> Splash

    state "Splash Screen<br/>(Operator Selection)" as Splash
    state "Scan / Cable Lookup<br/>(Main Hub)" as Hub
    state "Cable Info<br/>+ Action Menu" as CableAction

    Splash --> Hub: select operator

    %% --- Main Hub transitions ---
    Hub --> CableAction: scan serial (found)
    Hub --> NotFound: scan serial (not found)
    Hub --> SeriesSelect: 'r' register
    Hub --> Calibration: 'c' calibrate
    Hub --> InventoryDash: 'i' inventory
    Hub --> Wholesale: 'w' wholesale
    Hub --> WireLabels: 'p' wire labels
    Hub --> ShopifyScan: 's' shopify scan
    Hub --> CustLookup_F: 'f' fulfill orders
    Hub --> CustLookup_L: 'l' customer lookup
    Hub --> Splash: 'q' logout

    %% --- Cable Not Found ---
    state "Cable Not Found<br/>Prompt" as NotFound
    NotFound --> SeriesSelect: 'r' register
    NotFound --> Hub: Enter (continue)

    %% --- Cable Action Menu ---
    CableAction --> CableTest: 't' test
    CableAction --> CustLookup_A: 'a' assign to customer
    CableAction --> CableAction: 'u' unassign (with confirm)
    CableAction --> PrintLabel: 'p' print label
    CableAction --> PrintBarcode: 'b' print barcode
    CableAction --> PrintRegLabel: 'l' print reg label
    CableAction --> EditDescription: 'd' edit desc (MISC)
    CableAction --> SeriesSelect: 'e' re-register
    CableAction --> CableAction: scan next serial
    CableAction --> Hub: 'q' back

    state "Run Cable Test<br/>(TS or XLR)" as CableTest
    CableTest --> CableAction: done (reload record)

    state "Print Label" as PrintLabel
    PrintLabel --> CableAction: done

    state "Print Barcode" as PrintBarcode
    PrintBarcode --> CableAction: done

    state "Print Reg Label" as PrintRegLabel
    PrintRegLabel --> CableAction: done

    state "Edit Description<br/>(MISC only)" as EditDescription
    EditDescription --> CableAction: done

    %% --- Calibration ---
    state "Manual Calibration<br/>(TS + XLR)" as Calibration
    Calibration --> Hub: done
```

## Cable Registration Flow

```mermaid
stateDiagram-v2
    state "Series Selection<br/>(Step 1)" as SeriesSelect
    state "Color / Pattern<br/>(Step 2)" as ColorSelect
    state "MISC Cable Entry<br/>(Length Input)" as MiscEntry
    state "Length Selection<br/>(Step 3)" as LengthSelect
    state "Connector Selection<br/>(Step 4)" as ConnectorSelect
    state "Scan & Register<br/>(Intake Loop)" as Intake
    state "Cable Info<br/>+ Action Menu" as CableAction
    state "Scan / Cable Lookup<br/>(Main Hub)" as Hub

    SeriesSelect --> ColorSelect: select series
    SeriesSelect --> [*]: 'q' back

    ColorSelect --> MiscEntry: Miscellaneous
    ColorSelect --> LengthSelect: select color
    ColorSelect --> [*]: 'q' back

    MiscEntry --> Intake: enter length
    MiscEntry --> [*]: 'q' back

    LengthSelect --> ConnectorSelect: multiple connectors
    LengthSelect --> Intake: single connector
    LengthSelect --> [*]: 'q' back

    ConnectorSelect --> Intake: select connector
    ConnectorSelect --> [*]: 'q' back

    %% --- Intake scanning loop ---
    Intake --> CableAction: scan (success)
    Intake --> CableAction: scan (duplicate, unassigned)
    Intake --> Intake: scan (duplicate, assigned) - blocked
    Intake --> Hub: 'q' finish

    CableAction --> Intake: scan next / 'q'
```

## MISC Cable Description Sub-flow

```mermaid
stateDiagram-v2
    state "MISC Description<br/>Prompt" as DescPrompt
    state "Scan & Register<br/>(Intake Loop)" as Intake

    DescPrompt --> DescPrompt: text too long (re-prompt)
    DescPrompt --> Intake: enter description
    DescPrompt --> Intake: select existing type (1-N)
    DescPrompt --> [*]: 'q' cancel
```

## Customer & Assignment Flow

```mermaid
stateDiagram-v2
    state "Customer Lookup<br/>(Name Search)" as CustLookup
    state "Search Results<br/>(Customer List)" as CustResults
    state "Customer Detail<br/>(Info + Orders)" as CustDetail
    state "Order History" as Orders
    state "Assign Cables<br/>(Scan Loop)" as AssignCables
    state "Unassign Cable<br/>(Select + Confirm)" as UnassignCable
    state "Cable Info<br/>+ Action Menu" as CableAction

    %% --- Entry points ---
    CableAction --> CustLookup: 'a' assign

    CustLookup --> CustResults: search
    CustLookup --> [*]: 'q' back

    CustResults --> CustDetail: select customer
    CustResults --> CustDetail: Enter (auto-select, single result)
    CustResults --> CustLookup: 'n' new search
    CustResults --> [*]: 'q' back

    %% --- Auto-assign mode (from cable action 'a') ---
    CustDetail --> [*]: auto-assign cable (pop to hub)

    %% --- Normal mode ---
    CustDetail --> Orders: 'o' view orders
    CustDetail --> AssignCables: 'c' assign (no open orders)
    CustDetail --> OrderSelect: 'c' → 'y' (has open orders)
    CustDetail --> AssignCables: 'c' → 'n' (has open orders, skip)
    CustDetail --> UnassignCable: 'u' unassign cable
    CustDetail --> OrderSelect: 'f' fulfill order
    CustDetail --> [*]: Enter back

    Orders --> CustDetail: Enter back

    AssignCables --> AssignCables: scan serial (success)
    AssignCables --> AssignCables: scan serial (reassign confirmed)
    AssignCables --> CustLookup: 'q' done

    UnassignCable --> [*]: confirm unassign / cancel
```

## Order Fulfillment Flow

```mermaid
stateDiagram-v2
    state "Customer Lookup<br/>(Name Search)" as CustLookup
    state "Search Results<br/>(Customer List)" as CustResults
    state "Order Selection<br/>(Unfulfilled Orders)" as OrderSelect
    state "Order Fulfill Scan<br/>(Cable Scanning)" as FulfillScan
    state "Scan / Cable Lookup<br/>(Main Hub)" as Hub

    %% --- Entry from Hub 'f' (fulfillment mode) ---
    Hub --> CustLookup: 'f' fulfill orders

    CustLookup --> CustResults: search
    CustLookup --> [*]: 'q' back

    %% --- Fulfillment mode skips Customer Detail ---
    CustResults --> OrderSelect: select customer (fulfillment mode)
    CustResults --> CustLookup: 'n' new search
    CustResults --> [*]: 'q' back

    %% --- Order selection ---
    OrderSelect --> FulfillScan: select order
    OrderSelect --> FulfillScan: auto-select (single order)
    OrderSelect --> [*]: 'q' back / no orders

    %% --- Fulfillment scanning loop ---
    FulfillScan --> FulfillScan: scan cable (success, SKU matches)
    FulfillScan --> FulfillScan: scan cable (override assigned)
    FulfillScan --> FulfillScan: scan cable (error, continue)
    FulfillScan --> Hub: 'q' done (pop to hub)

    note right of FulfillScan
        Shows progress table per line item
        SKU validated against order
        'q' pops all the way to Hub
    end note
```

## Inventory Flow

```mermaid
stateDiagram-v2
    state "Inventory Dashboard<br/>(Series Summary)" as Dash
    state "Series Heatmap<br/>(Length x Pattern)" as Heatmap
    state "Production<br/>Suggestions" as Suggest

    Dash --> Heatmap: '1' Studio / '2' Tour
    Dash --> Suggest: 's' suggestions
    Dash --> [*]: 'q' back

    Heatmap --> Dash: any key
    Suggest --> Dash: any key
```

## Wholesale Flow

```mermaid
stateDiagram-v2
    state "Wholesale Batch<br/>(Scan Cables)" as Batch

    Batch --> Batch: scan serial (add to batch)
    Batch --> GenerateCodes: 'g' generate codes only
    Batch --> GenerateAndPrint: 'p' generate + print labels
    Batch --> [*]: 'q' cancel

    state "Generate Codes" as GenerateCodes
    GenerateCodes --> [*]: Enter (done)

    state "Generate + Print" as GenerateAndPrint
    GenerateAndPrint --> [*]: Enter (done)
```

## Utility Screens

```mermaid
stateDiagram-v2
    state "Wire Label Printer" as Wire
    state "Shopify Scan Mode<br/>(Paused Greenlight)" as ShopScan

    Wire --> Wire: enter SKU, print label
    Wire --> [*]: 'q' back

    ShopScan --> [*]: any key (resume)

    note right of ShopScan
        Disables Greenlight scanner on enter
        Re-enables scanner on exit
    end note
```

## Cable Test Detail (TS)

```mermaid
stateDiagram-v2
    state "Check Calibration" as CalCheck
    state "Continuity Test" as Cont
    state "Resistance Test" as Res
    state "Save Results" as Save
    state "Update Shopify" as Shopify

    [*] --> CalCheck
    CalCheck --> Cont: calibrated
    CalCheck --> CalibrationPrompt: not calibrated
    CalibrationPrompt --> Cont: calibrate
    CalibrationPrompt --> [*]: skip

    Cont --> Res: PASS
    Cont --> Save: FAIL
    Res --> Save: done
    Save --> Shopify: saved to DB
    Shopify --> [*]: done (auto-print label if printer available)
```

## Cable Test Detail (XLR)

```mermaid
stateDiagram-v2
    state "Check XLR Calibration" as CalCheck
    state "XLR Continuity<br/>(3x3 pin matrix)" as Cont
    state "Shell Bond Test" as Shell
    state "XLR Resistance<br/>(Pin 2 + Pin 3)" as Res
    state "Save Results" as Save
    state "Update Shopify" as Shopify

    [*] --> CalCheck
    CalCheck --> Cont: calibrated
    CalCheck --> XLRCalibrationPrompt: not calibrated
    XLRCalibrationPrompt --> Cont: calibrate
    XLRCalibrationPrompt --> [*]: skip

    Cont --> Shell: PASS (touring series)
    Cont --> Res: PASS (studio series)
    Cont --> Save: FAIL

    Shell --> Res: done
    Res --> Save: done
    Save --> Shopify: saved to DB
    Shopify --> [*]: done (auto-print label if printer available)
```

## External Dependencies

| Action | System | Screens |
|--------|--------|---------|
| Register cable | PostgreSQL | Intake |
| Save test results | PostgreSQL | Cable Test |
| Assign to customer | PostgreSQL | Assign Cables, Customer Detail, Order Fulfill |
| Update description | PostgreSQL + Shopify | Edit Description |
| Set inventory | Shopify API | Cable Test (on pass) |
| Create MISC product | Shopify API | Intake (MISC cables) |
| Customer search | Shopify API | Customer Lookup |
| Customer orders | Shopify API | Customer Detail, Order Selection |
| Order line items | Shopify API | Order Fulfill Scan |
| Wire product lookup | Shopify API | Wire Labels |
| Run continuity test | Arduino | Cable Test |
| Run resistance test | Arduino | Cable Test |
| Run shell bond test | Arduino | Cable Test (XLR) |
| Calibrate tester | Arduino | Calibration |
| Print cable label | TSC Printer | Print Label, Cable Test (auto) |
| Print barcode label | TSC Printer | Cable Action |
| Print reg code label | TSC Printer | Wholesale, Cable Action |
| Print wire label | TSC Printer | Wire Labels |
| Scan barcode | Zebra DS2208 | Hub, Intake, Assign, Wholesale, Order Fulfill |
| Webhook control | MQTT | Shopify Scan Mode |
