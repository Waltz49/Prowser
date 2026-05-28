tell application "Pixelmator Pro"
	activate
	set exportLocation to (POSIX file "__EXPORT_DIR__") as alias
	tell the front document
		-- Check if canvas is square
		set docWidth to width
		set docHeight to height
		if docWidth is not equal to docHeight then
			display alert "Canvas is not square." as warning
			return
		end if

		set visible of every layer to false

		set fileExtension to ".webp"

		-- Export top (first) layer as mask.webp
		set topLayer to item 1 of every layer
		set visible of topLayer to true
		export for web to (exportLocation as text) & "mask" & fileExtension as WebP
		set visible of topLayer to false

		-- Export second layer as base.webp
		set secondLayer to item 2 of every layer
		set visible of secondLayer to true
		export for web to (exportLocation as text) & "base" & fileExtension as WebP
		set visible of secondLayer to false

		-- Restore visibility for all layers
		set visible of every layer to true
	end tell
end tell
