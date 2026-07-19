/*
** file_audiomus.cpp
**
** Corridor 7 digitized sound archive support.
**
** AUDIOMUS.CO7 consists of 4096-byte pages.  The final page contains an
** offset/length directory for every page.  The page immediately before it
** contains 100 (first page, byte length) pairs describing the actual sounds.
** Sound data is unsigned 8-bit mono PCM played by the Wolf-derived driver at
** 9009 Hz (the effective rate produced by Corridor 7's DSP time constant).
*/

#include "wl_def.h"
#include "filesys.h"
#include "m_swap.h"
#include "resourcefile.h"
#include "w_wad.h"
#include "zstring.h"
#include "wl_main.h"

namespace
{
	static const unsigned int C7_PAGE_SIZE = 4096;
	static const unsigned int C7_SAMPLE_RATE = 9009;
	static const unsigned int C7_SOUND_COUNT = 100;

	struct FC7AudioMusSound : public FResourceLump
	{
		struct Chunk
		{
			unsigned int Offset;
			unsigned int Length;
		};

		static const char WavHeader[44];

		Chunk *Chunks;
		unsigned int NumChunks;
		unsigned int NumOriginalSamples;

		FC7AudioMusSound(unsigned int maxChunks)
			: Chunks(new Chunk[maxChunks]), NumChunks(0), NumOriginalSamples(0)
		{
		}

		~FC7AudioMusSound()
		{
			delete[] Chunks;
		}

		void AddChunk(unsigned int offset, unsigned int length)
		{
			Chunks[NumChunks].Offset = offset;
			Chunks[NumChunks].Length = length;
			++NumChunks;
			NumOriginalSamples += length;
		}

		void CalculateLumpSize()
		{
			if(NumOriginalSamples == 0)
			{
				LumpSize = 0;
				return;
			}

			const unsigned int outputSamples = static_cast<unsigned int>(
				(double(NumOriginalSamples) * param_samplerate) / C7_SAMPLE_RATE);
			LumpSize = sizeof(WavHeader) + outputSamples * 2;
		}

		void DoFinishRemap()
		{
			CalculateLumpSize();
		}

		int FillCache()
		{
			if(LumpSize == 0)
				return 1;

			const unsigned int outputSamples = (LumpSize - sizeof(WavHeader)) / 2;
			Cache = new char[LumpSize];
			memcpy(Cache, WavHeader, sizeof(WavHeader));
			*(DWORD *)(Cache + 4) = LittleLong(outputSamples * 2 + sizeof(WavHeader) - 8);
			*(DWORD *)(Cache + 24) = LittleLong(param_samplerate);
			*(DWORD *)(Cache + 28) = LittleLong(param_samplerate * 2);
			*(DWORD *)(Cache + sizeof(WavHeader) - 4) = LittleLong(outputSamples * 2);

			BYTE *original = new BYTE[NumOriginalSamples];
			unsigned int writePosition = 0;
			for(unsigned int i = 0; i < NumChunks; ++i)
			{
				Owner->Reader->Seek(Chunks[i].Offset, SEEK_SET);
				if(Owner->Reader->Read(original + writePosition, Chunks[i].Length) !=
					static_cast<long>(Chunks[i].Length))
				{
					delete[] original;
					delete[] Cache;
					Cache = NULL;
					return 0;
				}
				writePosition += Chunks[i].Length;
			}

			SWORD *output = reinterpret_cast<SWORD *>(Cache + sizeof(WavHeader));
			const double sourceStep = double(C7_SAMPLE_RATE) / param_samplerate;
			double sourcePosition = 0.0;
			for(unsigned int i = 0; i < outputSamples; ++i)
			{
				unsigned int sample = static_cast<unsigned int>(sourcePosition);
				if(sample >= NumOriginalSamples)
					sample = NumOriginalSamples - 1;
				const unsigned int next = sample + 1 < NumOriginalSamples ? sample + 1 : sample;
				const double fraction = sourcePosition - static_cast<unsigned int>(sourcePosition);
				const int currentValue = (int(original[sample]) - 128) << 8;
				const int nextValue = (int(original[next]) - 128) << 8;
				output[i] = LittleShort(static_cast<SWORD>(currentValue +
					fraction * (nextValue - currentValue)));
				sourcePosition += sourceStep;
			}

			delete[] original;
			return 1;
		}
	};

	const char FC7AudioMusSound::WavHeader[44] = {
		'R','I','F','F',0,0,0,0,'W','A','V','E',
		'f','m','t',' ',16,0,0,0,1,0,1,0,
		(char)0x82,0x17,0,0,0x37,0x04,0,0,2,0,16,0,
		'd','a','t','a',0,0,0,0
	};

	class FC7AudioMus : public FResourceFile
	{
		FC7AudioMusSound **Sounds;

	public:
		FC7AudioMus(const char *filename, FileReader *file)
			: FResourceFile(filename, file), Sounds(NULL)
		{
		}

		~FC7AudioMus()
		{
			if(Sounds != NULL)
			{
				for(unsigned int i = 0; i < NumLumps; ++i)
					delete Sounds[i];
				delete[] Sounds;
			}
		}

		bool Open(bool quiet)
		{
			const long fileLength = Reader->GetLength();
			if(fileLength < static_cast<long>(3 * C7_PAGE_SIZE) ||
				fileLength % C7_PAGE_SIZE != 0)
				return false;

			const unsigned int pageCount = fileLength / C7_PAGE_SIZE - 1;
			if(pageCount < 2 || 6 * pageCount > C7_PAGE_SIZE)
				return false;

			BYTE *directory = new BYTE[C7_PAGE_SIZE];
			Reader->Seek(pageCount * C7_PAGE_SIZE, SEEK_SET);
			if(Reader->Read(directory, C7_PAGE_SIZE) != C7_PAGE_SIZE)
			{
				delete[] directory;
				return false;
			}

			DWORD *offsets = new DWORD[pageCount];
			WORD *lengths = new WORD[pageCount];
			bool valid = true;
			for(unsigned int i = 0; i < pageCount; ++i)
			{
				offsets[i] = ReadLittleLong(directory + i * 4);
				lengths[i] = ReadLittleShort(directory + pageCount * 4 + i * 2);
				if(offsets[i] != i * C7_PAGE_SIZE || lengths[i] == 0 || lengths[i] > C7_PAGE_SIZE)
					valid = false;
			}
			delete[] directory;
			if(!valid || lengths[pageCount - 1] != C7_SOUND_COUNT * 8)
			{
				delete[] offsets;
				delete[] lengths;
				return false;
			}

			BYTE soundMap[C7_SOUND_COUNT * 8];
			Reader->Seek(offsets[pageCount - 1], SEEK_SET);
			if(Reader->Read(soundMap, sizeof(soundMap)) != sizeof(soundMap))
			{
				delete[] offsets;
				delete[] lengths;
				return false;
			}

			NumLumps = C7_SOUND_COUNT;
			Sounds = new FC7AudioMusSound *[NumLumps];
			memset(Sounds, 0, sizeof(*Sounds) * NumLumps);
			for(unsigned int i = 0; i < NumLumps; ++i)
			{
				const unsigned int startPage = ReadLittleLong(soundMap + i * 8);
				const unsigned int soundLength = ReadLittleLong(soundMap + i * 8 + 4);
				if(startPage >= pageCount - 1 || soundLength == 0)
				{
					valid = false;
					break;
				}

				unsigned int remaining = soundLength;
				unsigned int page = startPage;
				unsigned int chunkCount = 0;
				while(remaining > 0 && page < pageCount - 1)
				{
					if(lengths[page] > remaining)
					{
						valid = false;
						break;
					}
					remaining -= lengths[page++];
					++chunkCount;
				}
				if(!valid || remaining != 0)
				{
					valid = false;
					break;
				}

				Sounds[i] = new FC7AudioMusSound(chunkCount);
				Sounds[i]->Owner = this;
				char name[9];
				mysnprintf(name, sizeof(name), "C7DS%04u", i);
				Sounds[i]->LumpNameSetup(name);
				Sounds[i]->Namespace = ns_sounds;
				remaining = soundLength;
				page = startPage;
				while(remaining > 0)
				{
					Sounds[i]->AddChunk(offsets[page], lengths[page]);
					remaining -= lengths[page++];
				}
				Sounds[i]->CalculateLumpSize();
			}

			delete[] offsets;
			delete[] lengths;
			if(!valid)
				return false;

			if(!quiet)
				Printf(", %u Corridor 7 digitized sounds\n", NumLumps);
			return true;
		}

		FResourceLump *GetLump(int no)
		{
			return static_cast<unsigned int>(no) < NumLumps ? Sounds[no] : NULL;
		}
	};
}

FResourceFile *CheckAudioMus(const char *filename, FileReader *file, bool quiet)
{
	FString name(filename);
	const int slash = name.LastIndexOfAny("/\\:");
	if(slash >= 0)
		name = name.Mid(slash + 1);
	const int dot = name.LastIndexOf('.');
	if(dot >= 0)
		name = name.Left(dot);
	if(name.CompareNoCase("audiomus") != 0)
		return NULL;

	FResourceFile *resource = new FC7AudioMus(filename, file);
	if(resource->Open(quiet))
		return resource;
	resource->Reader = NULL;
	delete resource;
	return NULL;
}
