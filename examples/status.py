"""Print the state, ink levels and page counter of an HP printer."""

import asyncio
import sys

from hp_printer import HPPrinter


async def main(host: str) -> None:
    async with HPPrinter(host) as printer:
        data = await printer.update()
        print(f"{data.device.name if data.device else host}: {data.state.value}")
        if data.consumables:
            for ink in data.consumables.consumables:
                print(f"  {ink.color}: {ink.level}% ({ink.state})")
        if data.usage:
            print(f"  pages: {data.usage.total_impressions}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.50"))
