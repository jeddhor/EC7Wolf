# Charge packs used up as they are taken: GitHub #39

- **#39** after beta308, one Alien Charge Pack took energy capacity, and charge
  with it, to 999, and the pack stayed on the floor.

Baseline: EC7Wolf 1.0-beta308. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

## Cause

Not the rule from #34, which is right: a pack adds 100 capacity (CORR7CD.EXE
140f6, DS:80f0) up to 999, and is refused at 999. #34 made the pack a
CustomInventory, whose Pickup state calls `A_C7ChargePack`, and that exposed a
difference in ECWolf's CustomInventory.

ZDoom removes a CustomInventory item once its Pickup state succeeds, unless the
item has a Use state. ECWolf's `ACustomInventory::TryPickup` instead passed it on
to the ordinary inventory pickup, which put it in the player's inventory at its
default maxamount of 1. The first pack therefore worked. Every pack after it ran
its Pickup state, adding 100, and was then refused as a duplicate already at
its maximum. A refused pickup stays on the floor, so the pack was touched again
the next tic and added another 100, until capacity reached 999 and the
action itself refused it. Charge regenerates up to capacity, so it followed.

Every other CustomInventory in the tree (Wolf3D's and Noah's extra lives,
Noah's quiz items, Corridor 7's Adrenaline Boost) is ALWAYSPICKUP, which takes
a refused item anyway and hid this. The charge pack cannot be: DOS leaves it
lying at 999. The reporter's save already holds a pack in its inventory, as
every save made after a charge pack does.

## Fix

`ACustomInventory::TryPickup` follows ZDoom: once the Pickup state succeeds,
an item with no Use state goes away (`GoAwayAndDie`) instead of into the
inventory. No item in the tree has a Use state. Noah's quiz reads the item's
conversation after the pickup; `Destroy` is deferred and a placed item is only
hidden, so the item is still there to read. A pack already held in an old save
no longer matters.

## Saves keep old caps

The reporter's save also showed `C7BodyArmor=200/65535` and
`C7EnergyCapacity=100/100`. An item's maxamount is saved with it, so a save
keeps the caps of the build that wrote it: #38's 999 armor cap did not reach a
save made before beta308, and armor in it could still pass 999. Loading a
Corridor 7 save now sets both items' maxamount to the definition's (neither is
ever raised in play) and brings armor above 999 down to 999. The reporter's save
loads with `C7BodyArmor=200/999` and `C7EnergyCapacity=100/999`.

## Tests

`corridor7_health_energy` lays ten packs in a row: capacity steps through 100,
200, ... 900 and 999, never more than 100 at once, nine packs are taken and the
tenth, at 999, stays. On the beta308 binary it fails: capacity jumps from 800 to
999 between two trace lines and only one pack is taken. The exit vortex, also a
CustomInventory, still ends the floor (lab check), and the corridor7, bot_items
and multiplayer_rules gates pass.
