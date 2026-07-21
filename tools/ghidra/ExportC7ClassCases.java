// Export the otherwise-unresolved computed-jump cases in Corridor 7's
// common alien spawner.

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class ExportC7ClassCases extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length != 1)
			throw new IllegalArgumentException("usage: OUTPUT");

		Address table = currentProgram.getAddressFactory().getAddress("2454:05f1");
		try (PrintWriter output = new PrintWriter(new File(args[0]))) {
			for (int actorClass = 0; actorClass <= 20; ++actorClass) {
				int lo = getByte(table.add(actorClass * 2)) & 0xff;
				int hi = getByte(table.add(actorClass * 2 + 1)) & 0xff;
				int storedOffset = lo | (hi << 8);
				Address target = currentProgram.getAddressFactory().getAddress(
					String.format("2454:%04x", storedOffset));
				output.printf("CLASS %d target=%s%n", actorClass, target);
				disassemble(target);
				Address cursor = target;
				for (int count = 0; count < 80; ++count) {
					Instruction instruction = getInstructionAt(cursor);
					if (instruction == null)
						break;
					output.printf("  %s  %s%n", instruction.getAddress(), instruction);
					String mnemonic = instruction.getMnemonicString();
					if (mnemonic.equals("RETF") || mnemonic.equals("RET") ||
						(mnemonic.equals("JMP") && count > 0))
						break;
					cursor = instruction.getMaxAddress().next();
				}
			}
			String[] specials = { "2454:061b", "2454:0c86", "2454:0cee" };
			for (String root : specials) {
				Address cursor = currentProgram.getAddressFactory().getAddress(root);
				output.println("SPECIAL " + root);
				disassemble(cursor);
				for (int count = 0; count < 120; ++count) {
					Instruction instruction = getInstructionAt(cursor);
					if (instruction == null)
						break;
					output.printf("  %s  %s%n", instruction.getAddress(), instruction);
					if (instruction.getMnemonicString().equals("RETF"))
						break;
					cursor = instruction.getMaxAddress().next();
				}
			}
		}
	}
}
