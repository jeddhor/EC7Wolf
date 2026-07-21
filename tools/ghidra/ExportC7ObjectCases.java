// Disassemble and export the Corridor 7 plane-1 object switch cases.
// Ghidra does not automatically follow this 16-bit computed jump table.

import java.io.File;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;

public class ExportC7ObjectCases extends GhidraScript {
	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length != 1)
			throw new IllegalArgumentException("usage: OUTPUT");

		Address table = toAddr("16a2:0834");
		Memory memory = currentProgram.getMemory();
		Set<Long> targets = new HashSet<>();
		for (int object = 19; object <= 375; ++object) {
			Address entry = table.add((object - 19) * 2L);
			int offset = memory.getByte(entry) & 0xff;
			offset |= (memory.getByte(entry.add(1)) & 0xff) << 8;
			if (offset >= 0x0213 && offset <= 0x0816)
				targets.add((long) offset);
		}

		for (long offset : targets)
			disassemble(toAddr(String.format("16a2:%04x", offset)));

		AddressSet range = new AddressSet(toAddr("16a2:0213"), toAddr("16a2:0816"));
		try (PrintWriter output = new PrintWriter(new File(args[0]))) {
			InstructionIterator instructions =
				currentProgram.getListing().getInstructions(range, true);
			while (instructions.hasNext()) {
				Instruction instruction = instructions.next();
				output.printf("%s  %-30s ; %s", instruction.getAddress(),
					instruction.toString(), instruction.getFlowType());
				Address[] flows = instruction.getFlows();
				if (flows.length != 0) {
					output.print(" ->");
					for (Address flow : flows)
						output.print(" " + flow);
				}
				output.println();
			}
		}
	}
}
