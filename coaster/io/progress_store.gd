class_name ProgressStore
extends RefCounted
## Which contracts the player has finished (best stars) and which coaster
## types are unlocked. Saved to user://progress.json.

const PATH := "user://progress.json"
const STARTING_TYPES := [CoasterTypes.Id.STEEL, CoasterTypes.Id.WOODEN]

var stars := {}          # contract id -> best stars (1..3)
var path := PATH


static func load_or_new(p_path: String = PATH) -> ProgressStore:
	var s := ProgressStore.new()
	s.path = p_path
	if FileAccess.file_exists(p_path):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(p_path))
		if parsed is Dictionary and parsed.get("stars") is Dictionary:
			for k in parsed["stars"]:
				s.stars[str(k)] = int(parsed["stars"][k])
	return s


func save() -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"stars": stars}))


func best(id: String) -> int:
	return int(stars.get(id, 0))


## Records a result; returns the coaster type newly unlocked by it, or -1.
func record(id: String, new_stars: int) -> int:
	var before := unlocked_types()
	if new_stars > best(id):
		stars[id] = new_stars
		save()
	for t in unlocked_types():
		if not before.has(t):
			return t
	return -1


## A contract is open once the previous one has at least one star.
func is_available(index: int) -> bool:
	return index == 0 or best(Contracts.LIST[index - 1]["id"]) > 0


func unlocked_types() -> Array:
	var out := STARTING_TYPES.duplicate()
	for c in Contracts.LIST:
		if c.has("unlocks") and best(c["id"]) > 0 and not out.has(c["unlocks"]):
			out.append(c["unlocks"])
	return out


func total_stars() -> int:
	var t := 0
	for k in stars:
		t += int(stars[k])
	return t
