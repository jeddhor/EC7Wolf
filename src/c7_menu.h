/*
** c7_menu.h
**
** The Corridor 7 menu shell: splash art bleeding into black on the left, the
** menu itself in the cleared space on the right.
**
** This is a skin, not a menu hierarchy. Menu::draw() delegates here when the
** skin is active, so every existing menu -- sound, display, controls, the
** resolution list -- picks up the new look without being rebuilt, and the item
** and listener model underneath is untouched.
*/

#ifndef __C7_MENU_H__
#define __C7_MENU_H__

class Menu;

// True when the Corridor 7 menu skin should be used. False for every other
// supported game, which keeps their menus exactly as they were.
bool C7Menu_Active();

// Paints `menu` in the Corridor 7 shell. Returns false if the skin cannot draw
// (missing font or splash art), so the caller can fall back to the stock
// presentation rather than showing nothing.
bool C7Menu_Draw(const Menu *menu);

// Transitions between two menu screens by fading only the menu column, leaving
// the splash art standing. Moving between screens changes nothing on the left,
// so dipping the whole display to black to swap a list of words throws away the
// one part of the picture that was never going to change.
//
// `out` darkens the column to black; false brings it back, drawing `menu` as it
// goes so the caller does not draw it first -- a full-strength draw before the
// fade would flash the new screen for a frame.
//
// Returns false when the skin is not drawing, so the caller can fall back to the
// palette fade. Callers must also not use this while the screen is already
// faded: there the whole picture has to come back, not just the column.
bool C7Menu_FadeColumn(const Menu *menu, bool out);

// Edits a text field in this shell, drawing it on the row it belongs to rather
// than at the stock menu's coordinates. `setValue` writes the in-progress text
// into the item so that the shell's own value column renders it -- passed in
// because m_classes.h is not visible from here.
//
// Returns true if the edit was accepted, false if it was abandoned.
bool C7Menu_LineInput(const Menu *menu, class MenuItem *item, class FString &text,
	unsigned int maxLength, void (*setValue)(class MenuItem *, const class FString &));

// Drops the cached backdrop. Called on resolution and palette changes, since
// the backdrop is composited for a specific screen size.
void C7Menu_Invalidate();

#endif
