O3 — Upgrade Review 2 · Appearance

Open "Open O3 Review.cmd" to explore the upgrade with fictional sample information.
The sample is kept beside this review in review-workspace. Your installed O3 workspace
and original Candidate 6 package are not used or replaced.

Start with Mail:
  Unanswered — mail addressed to you with no reply from you found in the saved mail.
  Waiting for replies — mail you sent with no later reply found.
  All mail — all saved conversations, including ones O3 could not fully check.

Open a message to read it. Related information offers the other messages in its
conversation and its connections. No reply needed and Stop waiting are local choices;
Undo reverses them. They do not send mail. New messages can bring a conversation back.

Personalize previews your choices before saving a view. Saved views lets you reopen,
rename or remove your own views. The default views remain available.

People, Documents, Calendar and Projects work without setting up rules or custom views.
Projects find related information already saved in O3. Connections has a readable map,
a list, and a way to return to the item you started with.

Settings → Appearance now includes 24 palettes: 12 light and 12 dark. Browse the visual
theme cards, choose an accent color, or turn on stronger contrast. Colors are adjusted
when needed to keep labels readable.

Text offers five sizes, three lettering styles, and separate reading font, size and
line-spacing choices. Layout controls list spacing, a quiet layout using the Menu
button, and reading width. My looks keeps your favorite combinations. Everything is
previewed until you choose Save appearance. Cancel restores your previous choices;
Restore default appearance is also a preview and does not erase your saved looks.

The review launcher now shows the matching welcome screen while your workspace opens,
then closes it when the workspace is ready. Preview it or turn it off in Appearance →
Layout. The application window and Windows taskbar use the O3 icon.

This is a development review of the application, using the existing local Python 3.12.10
and PySide6/Qt 6.9.2 verification environment. It is not an installer or the approved
runtime/runner. The native launcher source and approved runner are still needed to
integrate and qualify the executable icon and startup splash. Editable icon and splash
assets are included; the separate review launcher has its own working welcome screen.

Your own information must already be exported in the supported O3 folder format.
This review does not add a live Outlook/Gmail connection or a general-purpose importer.
Draft a reply creates a local draft only. Checking files cannot prove the state of a live
mailbox. O3 shows incomplete evidence explicitly instead of treating it as answered mail.

Developers: review_app.py requires --example or an explicit --workspace directory.
BUILD_REVIEW_MANIFEST.json records the exact application files in this review archive.
The inherited native executable/bootstrap is intentionally absent from the review ZIP;
its integration remains separate from this application review.
