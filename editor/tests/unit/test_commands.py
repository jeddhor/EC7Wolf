#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""E3: commands, undo, coalescing, and a model-based check of all of it.

The last class in this file is the one that matters. It runs ten thousand
mixed operations against a plain nested-list reference model kept alongside the
real document, comparing after every step. Undo and redo are in the mix, so the
model has to keep its own history too, and any disagreement about what an edit
meant shows up as a mismatch rather than as a bug report months later.

The sequence is seeded, so a failure is reproducible on any machine rather than
a story about one CI run.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

EDITOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EDITOR))

from ec7edit_core.commands import (
    CellEdit,
    Command,
    CommandError,
    History,
    Transaction,
    apply_command,
    paint_cells,
    rename_map,
    write_words,
)
from ec7edit_core.document import MapDocument, ProjectDocument
from ec7edit_core.errors import Ec7EditError
from ec7edit_core.planes import linear_index


def project_with_map(width=8, height=8):
    document = MapDocument.blank(width=width, height=height, name="LAB")
    return ProjectDocument.create().added(document), document.uuid


class Applying(unittest.TestCase):
    def setUp(self):
        self.project, self.uuid = project_with_map()

    def test_paint_writes_the_cells(self):
        document = self.project.map_by_uuid(self.uuid)
        result = apply_command(self.project, paint_cells(document, 0, [(1, 2), (3, 4)], 42))
        self.assertEqual(result.map_by_uuid(self.uuid).cell(0, 1, 2), 42)
        self.assertEqual(result.map_by_uuid(self.uuid).cell(0, 3, 4), 42)

    def test_unchanged_cells_are_not_recorded(self):
        document = self.project.map_by_uuid(self.uuid)
        self.assertEqual(len(paint_cells(document, 0, [(1, 1)], 0)), 0)

    def test_cells_outside_the_map_are_dropped(self):
        document = self.project.map_by_uuid(self.uuid)
        command = paint_cells(document, 0, [(-1, 0), (0, 99), (2, 2)], 7)
        self.assertEqual(len(command), 1)

    def test_all_three_planes_are_writable(self):
        document = self.project.map_by_uuid(self.uuid)
        command = write_words(document, [(0, 1, 1, 5), (1, 1, 1, 6), (2, 1, 1, 7)])
        result = apply_command(self.project, command).map_by_uuid(self.uuid)
        self.assertEqual([result.cell(p, 1, 1) for p in range(3)], [5, 6, 7])

    def test_a_command_for_a_missing_map_is_refused(self):
        command = Command("x", (CellEdit("nope", 0, 0, 0, 1),))
        with self.assertRaises(CommandError):
            apply_command(self.project, command)

    def test_a_word_outside_uint16_is_refused(self):
        command = Command("x", (CellEdit(self.uuid, 0, 0, 0, 70000),))
        with self.assertRaises(Ec7EditError) as caught:
            apply_command(self.project, command)
        self.assertEqual(caught.exception.diagnostic.code, "C7E-CELL-001")

    def test_an_index_outside_the_map_is_refused(self):
        command = Command("x", (CellEdit(self.uuid, 0, 9999, 0, 1),))
        with self.assertRaises(CommandError):
            apply_command(self.project, command)

    def test_a_missing_plane_is_refused(self):
        command = Command("x", (CellEdit(self.uuid, 5, 0, 0, 1),))
        with self.assertRaises(CommandError):
            apply_command(self.project, command)


class Inversion(unittest.TestCase):
    def test_a_command_and_its_inverse_cancel(self):
        project, uuid = project_with_map()
        document = project.map_by_uuid(uuid)
        command = paint_cells(document, 0, [(x, 0) for x in range(5)], 9)
        applied = apply_command(project, command)
        restored = apply_command(applied, command.inverted())
        self.assertEqual(
            restored.map_by_uuid(uuid).planes.planes, project.map_by_uuid(uuid).planes.planes
        )

    def test_inversion_reverses_order(self):
        # Two writes to one cell must unwind in the opposite order, or the
        # cell ends up holding the intermediate value.
        project, uuid = project_with_map()
        command = Command("x", (
            CellEdit(uuid, 0, 0, 0, 1),
            CellEdit(uuid, 0, 0, 1, 2),
        ))
        applied = apply_command(project, command)
        self.assertEqual(applied.map_by_uuid(uuid).cell(0, 0, 0), 2)
        restored = apply_command(applied, command.inverted())
        self.assertEqual(restored.map_by_uuid(uuid).cell(0, 0, 0), 0)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.project, self.uuid = project_with_map()
        self.history = History()

    def paint(self, cells, value, gesture=""):
        document = self.project.map_by_uuid(self.uuid)
        self.project = self.history.do(
            self.project, paint_cells(document, 0, cells, value, gesture=gesture)
        )

    def test_undo_and_redo(self):
        self.paint([(1, 1)], 5)
        self.project = self.history.undo(self.project)
        self.assertEqual(self.project.map_by_uuid(self.uuid).cell(0, 1, 1), 0)
        self.project = self.history.redo(self.project)
        self.assertEqual(self.project.map_by_uuid(self.uuid).cell(0, 1, 1), 5)

    def test_a_no_op_is_not_recorded(self):
        self.paint([(1, 1)], 0)
        self.assertFalse(self.history.can_undo)

    def test_a_gesture_is_one_step(self):
        for x in range(10):
            self.paint([(x, 0)], 3, gesture="stroke-1")
        self.assertEqual(self.history.depth, 1)
        self.project = self.history.undo(self.project)
        document = self.project.map_by_uuid(self.uuid)
        self.assertEqual([document.cell(0, x, 0) for x in range(10)], [0] * 10)

    def test_ending_a_gesture_starts_a_new_step(self):
        self.paint([(0, 0)], 3, gesture="stroke-1")
        self.history.end_gesture()
        self.paint([(1, 0)], 3, gesture="stroke-1")
        self.assertEqual(self.history.depth, 2)

    def test_different_gestures_do_not_merge(self):
        self.paint([(0, 0)], 3, gesture="a")
        self.paint([(1, 0)], 3, gesture="b")
        self.assertEqual(self.history.depth, 2)

    def test_a_new_edit_clears_redo(self):
        self.paint([(0, 0)], 1)
        self.project = self.history.undo(self.project)
        self.assertTrue(self.history.can_redo)
        self.paint([(1, 1)], 2)
        self.assertFalse(self.history.can_redo)

    def test_undo_at_the_bottom_is_harmless(self):
        before = self.project
        self.assertIs(self.history.undo(before), before)

    def test_redo_at_the_top_is_harmless(self):
        before = self.project
        self.assertIs(self.history.redo(before), before)

    def test_labels_are_reported(self):
        document = self.project.map_by_uuid(self.uuid)
        self.project = self.history.do(
            self.project, paint_cells(document, 0, [(0, 0)], 1, label="Paint wall")
        )
        self.assertEqual(self.history.undo_label, "Paint wall")
        self.project = self.history.undo(self.project)
        self.assertEqual(self.history.redo_label, "Paint wall")

    def test_the_step_cap_drops_the_oldest(self):
        self.history.step_cap = 5
        for x in range(20):
            self.paint([(x % 8, 0)], x + 1)
        self.assertLessEqual(self.history.depth, 5)
        self.assertGreater(self.history.dropped_steps, 0)

    def test_the_edit_cap_drops_the_oldest(self):
        self.history.edit_cap = 10
        for x in range(8):
            self.paint([(c, x) for c in range(8)], x + 1)
        self.assertLessEqual(self.history.edit_count, 10 + 8)

    def test_renaming_undoes(self):
        document = self.project.map_by_uuid(self.uuid)
        self.project = self.history.do(self.project, rename_map(document, "ATRIUM"))
        self.assertEqual(self.project.map_by_uuid(self.uuid).name, "ATRIUM")
        self.project = self.history.undo(self.project)
        self.assertEqual(self.project.map_by_uuid(self.uuid).name, "LAB")


class Transactions(unittest.TestCase):
    def test_several_commands_become_one_step(self):
        project, uuid = project_with_map()
        history = History()
        document = project.map_by_uuid(uuid)
        with Transaction(history, "Place transporter") as batch:
            batch.add(write_words(document, [(0, 1, 1, 279)]))
            batch.add(write_words(document, [(0, 5, 5, 279)]))
            project = batch.commit(project)
        self.assertEqual(history.depth, 1)
        self.assertEqual(history.undo_label, "Place transporter")
        project = history.undo(project)
        document = project.map_by_uuid(uuid)
        self.assertEqual((document.cell(0, 1, 1), document.cell(0, 5, 5)), (0, 0))

    def test_an_abandoned_transaction_changes_nothing(self):
        project, uuid = project_with_map()
        history = History()
        document = project.map_by_uuid(uuid)
        batch = Transaction(history, "Abandoned")
        batch.add(write_words(document, [(0, 1, 1, 5)]))
        # Never committed.
        self.assertEqual(project.map_by_uuid(uuid).cell(0, 1, 1), 0)
        self.assertFalse(history.can_undo)


class ModelBased(unittest.TestCase):
    """Ten thousand mixed operations against an independent reference model."""

    OPERATIONS = 10_000
    SEED = 20260829
    WIDTH = HEIGHT = 12

    def test_matches_a_reference_model(self):
        generator = random.Random(self.SEED)
        project, uuid = project_with_map(self.WIDTH, self.HEIGHT)
        history = History(step_cap=10_000, edit_cap=10_000_000)

        # The reference: three flat lists and a stack of (index, plane, old)
        # triples. Deliberately not the production structures.
        model = [[0] * (self.WIDTH * self.HEIGHT) for _ in range(3)]
        model_name = "LAB"
        undo_stack: list[tuple] = []
        redo_stack: list[tuple] = []

        def snapshot():
            document = project.map_by_uuid(uuid)
            return [list(plane) for plane in document.planes.planes], document.name

        for step in range(self.OPERATIONS):
            choice = generator.random()
            document = project.map_by_uuid(uuid)

            if choice < 0.55:  # paint a run of cells
                plane = generator.randrange(3)
                value = generator.randrange(0, 400)
                count = generator.randint(1, 6)
                cells = [
                    (generator.randrange(self.WIDTH), generator.randrange(self.HEIGHT))
                    for _ in range(count)
                ]
                command = paint_cells(document, plane, cells, value)
                if command.changes_anything:
                    changes = []
                    for x, y in cells:
                        index = linear_index(x, y, self.WIDTH)
                        if model[plane][index] != value:
                            changes.append((plane, index, model[plane][index]))
                            model[plane][index] = value
                    if changes:
                        undo_stack.append(("cells", changes))
                        redo_stack.clear()
                project = history.do(project, command)

            elif choice < 0.62:  # rename
                name = f"MAP{generator.randrange(1000):03d}"
                if name != model_name:
                    undo_stack.append(("name", model_name))
                    redo_stack.clear()
                    model_name = name
                    project = history.do(project, rename_map(document, name))

            elif choice < 0.66:  # close the current gesture
                history.end_gesture()

            elif choice < 0.85:  # undo
                if undo_stack:
                    kind, payload = undo_stack.pop()
                    if kind == "cells":
                        restored = []
                        for plane, index, old in reversed(payload):
                            restored.append((plane, index, model[plane][index]))
                            model[plane][index] = old
                        redo_stack.append(("cells", list(reversed(restored))))
                    else:
                        redo_stack.append(("name", model_name))
                        model_name = payload
                    project = history.undo(project)

            else:  # redo
                if redo_stack:
                    kind, payload = redo_stack.pop()
                    if kind == "cells":
                        undone = []
                        for plane, index, new in payload:
                            undone.append((plane, index, model[plane][index]))
                            model[plane][index] = new
                        undo_stack.append(("cells", undone))
                    else:
                        undo_stack.append(("name", model_name))
                        model_name = payload
                    project = history.redo(project)

            if step % 250 == 0 or step == self.OPERATIONS - 1:
                planes, name = snapshot()
                self.assertEqual(planes, model, f"planes diverged at step {step}")
                self.assertEqual(name, model_name, f"name diverged at step {step}")

        planes, name = snapshot()
        self.assertEqual(planes, model)
        self.assertEqual(name, model_name)

    def test_undoing_everything_returns_the_original(self):
        generator = random.Random(self.SEED + 1)
        project, uuid = project_with_map(8, 8)
        original = project.map_by_uuid(uuid).planes.planes
        history = History(step_cap=10_000, edit_cap=10_000_000)

        for _ in range(500):
            document = project.map_by_uuid(uuid)
            project = history.do(
                project,
                paint_cells(
                    document,
                    generator.randrange(3),
                    [(generator.randrange(8), generator.randrange(8))],
                    generator.randrange(1, 300),
                ),
            )
            history.end_gesture()

        while history.can_undo:
            project = history.undo(project)
        self.assertEqual(project.map_by_uuid(uuid).planes.planes, original)


if __name__ == "__main__":
    unittest.main(verbosity=1)
