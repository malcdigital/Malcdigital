class_name CoasterStorage
extends RefCounted
## Saves and loads coasters as JSON files in the user data folder
## (user://coasters/). On desktop that is the OS app-data folder; on iOS and
## Android it is the app's private storage.

const DIR := "user://coasters"


static func _ensure_dir() -> void:
	if not DirAccess.dir_exists_absolute(DIR):
		DirAccess.make_dir_recursive_absolute(DIR)


static func file_name_for(coaster_name: String) -> String:
	var safe := ""
	for c in coaster_name.strip_edges():
		safe += c if (c.is_valid_identifier() or c.is_valid_int() or c == "-") else "_"
	if safe.is_empty():
		safe = "coaster"
	return safe.to_lower()


static func save(data: TrackData) -> Error:
	_ensure_dir()
	var path := "%s/%s.json" % [DIR, file_name_for(data.name)]
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return FileAccess.get_open_error()
	f.store_string(JSON.stringify(data.to_dict(), "\t"))
	f.close()
	return OK


## Returns [{"name": display name, "file": file name without extension}], newest first.
static func list() -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	_ensure_dir()
	var d := DirAccess.open(DIR)
	if d == null:
		return out
	for fname in d.get_files():
		if not fname.ends_with(".json"):
			continue
		var path := "%s/%s" % [DIR, fname]
		var data := _read(path)
		out.append({
			"file": fname.get_basename(),
			"name": data.name if data != null else fname.get_basename(),
			"modified": FileAccess.get_modified_time(path),
		})
	out.sort_custom(func(a, b): return a["modified"] > b["modified"])
	return out


static func load_coaster(file: String) -> TrackData:
	return _read("%s/%s.json" % [DIR, file])


static func delete(file: String) -> void:
	DirAccess.remove_absolute("%s/%s.json" % [DIR, file])


static func _read(path: String) -> TrackData:
	if not FileAccess.file_exists(path):
		return null
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		return null
	var t := TrackData.from_dict(parsed)
	return t if t.points.size() >= 2 else null
