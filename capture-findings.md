# Findings from the supplied ARCCONF outputs

Both original files are preserved unchanged in the project root. Their names do
not determine their content type.

## schema.json

A `Controllers found: 0` banner precedes a JSON document. The existing framed JSON
parser handles this. The document describes fields even without attached
controllers; it is not an inventory or proof of a particular card's capabilities.

The vendor catalog describes entities such as `/System/Controller`,
`/System/Channel/HardDrive` and `/System/LogicalDrive`. These are **schema entity
paths**, not verified pointers into a live GETCONFIGJSON inventory. It uses
vendor nesting and `enumDescriptions`; a generic JSON Schema validator alone
would not establish the live record layout.

Useful field definitions:

| Entity | Fields / value descriptions |
|---|---|
| Controller | `controllerID`, `serialNumber`, `deviceName`; `controllerStatus` 0 = Optimal; `controllerState` 0 = OK |
| Physical drive | `controllerID`, `channelID`, `deviceID`, `serialNumber`; `state` 1 = Online, 0 = Ready/unconfigured |
| Logical drive | `controllerID`, `logicalDriveID`; `state` 2 = OK; `raidLevel` descriptions map 16 to RAID 6 |

Status codes differ between entity types. Physical Ready is not the same as an
online RAID member. Controller status alone does not establish cache, battery,
encryption, initialization or whole-array health.

There are inconsistencies within the catalog: `LogicalDrive.raidLevel` describes
16 as RAID 6 and 17 as RAID 60 but omits both from its enum list. Some numeric
fields also list enum values as strings. The library preserves raw codes and
reports label/list disagreement rather than silently correcting the schema or
assuming the RAID number equals the raw code. The generated schema report lists
all description/list discrepancies detected; this is not a full schema validator.

The regression fixture `tests/fixtures/schema.excerpt.json` contains only selected
field definitions extracted from the supplied schema. It is not a live inventory.

## system-with-no-controllers.json

This is text, not JSON. It reports `Controllers found: 0`, followed by
`Invalid arguments.` and command usage. The reason for the argument rejection
cannot be established from this output alone. Neither a zero banner nor a schema
capture proves that the actual server lacks controllers: driver, privilege,
execution environment and hardware access still matter.

The CLI now classifies this as a command error with a reported controller count
of zero. Live Runner raises a structured InvalidArgumentsError for this response,
and monitor exposes that count under errors without fabricating a successful
empty inventory. Raw command output is not stored in the exception.

## Remaining capture needed

On the target server with its controllers visible, capture GETCONFIGJSON ALL
using an output filename ending in .json, along with LIST and GETVERSION. Keep
stdout/stderr diagnostics separate from the JSON output file. A populated
capture will establish record nesting/cardinality, actual field types, controller
index correspondence, and which fields are present for this firmware. Until then
the synthetic inventory adapter remains explicitly unvalidated; no guessed live
adapter or write authorization has been added.
