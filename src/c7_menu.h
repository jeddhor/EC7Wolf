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

// Drops the cached backdrop. Called on resolution and palette changes, since
// the backdrop is composited for a specific screen size.
void C7Menu_Invalidate();

#endif
