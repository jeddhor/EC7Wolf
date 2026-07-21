// Decode Corridor 7's 18-byte Wolf3D statetype records for every alien class.

import java.io.File;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class ExportC7StateChains extends GhidraScript {
	private int word(Address address) throws Exception {
		return (getByte(address) & 0xff) | ((getByte(address.add(1)) & 0xff) << 8);
	}

	private void printState(PrintWriter output, Address state, String prefix)
		throws Exception {
		int rotate = word(state);
		int shape = word(state.add(2));
		int ticks = word(state.add(4));
		int thinkOff = word(state.add(6));
		int thinkSeg = word(state.add(8));
		int actionOff = word(state.add(10));
		int actionSeg = word(state.add(12));
		int nextOff = word(state.add(14));
		int nextSeg = word(state.add(16));
		output.printf("  %s%s rotate=%d shape=%d ticks=%d think=%04x:%04x " +
			"action=%04x:%04x next=%04x:%04x%n", prefix, state, rotate, shape,
			ticks, thinkSeg, thinkOff, actionSeg, actionOff, nextSeg, nextOff);
	}

	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length != 1)
			throw new IllegalArgumentException("usage: OUTPUT");
		String[] roots = {
			"397c:0000", "39ac:0000", "39c7:0000", "39ee:0000",
			"3a15:0000", "3a3c:0000", "3a3c:0012", "3a3c:0024",
			"3a3c:0036", "3a76:0000", "3a95:0000", "3b49:0000",
			"3c9c:0000", "3b5f:0000", "3b79:0000", "3af9:0000",
			"3b12:0000", "3ace:0000", "3ae8:0000", "3b2a:0000"
		};
		try (PrintWriter output = new PrintWriter(new File(args[0]))) {
			for (String root : roots) {
				output.println("ROOT " + root);
				Address state = currentProgram.getAddressFactory().getAddress(root);
				Set<Long> visited = new HashSet<>();
				for (int count = 0; state != null && count < 128; ++count) {
					if (!visited.add(state.getOffset())) {
						output.println("  LOOP " + state);
						break;
					}
					printState(output, state, "");
					int nextOff = word(state.add(14));
					int nextSeg = word(state.add(16));
					if (nextSeg == 0 && nextOff == 0)
						break;
					state = currentProgram.getAddressFactory().getAddress(
						String.format("%04x:%04x", nextSeg, nextOff));
				}
			}

			String[] sequential = {
				"397c:0000", "39ac:0000", "39c7:0000", "39ee:0000",
				"3a15:0000", "3a3c:0000", "3a76:0000", "3a95:0000",
				"3ace:0000", "3ae8:0000", "3af9:0000", "3b12:0000",
				"3b2a:0000", "3b49:0000", "3b5f:0000", "3b79:0000",
				"3c9c:0000"
			};
			for (String root : sequential) {
				output.println("SEQUENTIAL " + root);
				Address base = currentProgram.getAddressFactory().getAddress(root);
				for (int record = 0; record < 100; ++record) {
					Address state = base.add(record * 18L);
					int rotate = word(state);
					int shape = word(state.add(2));
					int ticks = word(state.add(4));
					if (rotate > 1 || shape > 2000 || ticks > 1000)
						break;
					printState(output, state, String.format("+%04x ", record * 18));
				}
			}
		}
	}
}
