class_name EditHistory
extends RefCounted
## Undo/redo by snapshots. Each edit stores the whole track as a dictionary
## *before* the change. Tracks are small (tens of points), so a snapshot is a
## few KB and this is far simpler and more robust than per-command inverses.

const MAX_STEPS := 100

var _undo: Array[Dictionary] = []
var _redo: Array[Dictionary] = []


## Call BEFORE modifying `data`.
func push(data: TrackData) -> void:
	_undo.append(data.to_dict())
	if _undo.size() > MAX_STEPS:
		_undo.pop_front()
	_redo.clear()


func can_undo() -> bool:
	return not _undo.is_empty()


func can_redo() -> bool:
	return not _redo.is_empty()


## Returns the restored track, or null if there is nothing to undo.
func undo(current: TrackData) -> TrackData:
	if _undo.is_empty():
		return null
	_redo.append(current.to_dict())
	return TrackData.from_dict(_undo.pop_back())


func redo(current: TrackData) -> TrackData:
	if _redo.is_empty():
		return null
	_undo.append(current.to_dict())
	return TrackData.from_dict(_redo.pop_back())


func clear() -> void:
	_undo.clear()
	_redo.clear()
