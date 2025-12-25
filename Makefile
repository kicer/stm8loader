# Toolchain and programmer paths
TOOLCHAIN ?= /opt/Developer/sdcc/bin
ISPTOOL ?= /opt/Developer/stm8flash

# MCU configuration
MCU  = stm8s103f3
ARCH = stm8

# Compilation settings
F_CPU   ?= 2000000
TARGET  ?= $(lastword $(subst /, ,$(CURDIR)))

# Bootloader mode control
ENABLE_OPTION_BOOTLOADER ?= 1

# Directory structure
BUILD_DIR  = objects
SRC_DIR    = src
BSP_DIR    = bsp
SCRIPTS_DIR = scripts
BSP_INC_DIR = $(BSP_DIR)/inc
SRC_INC_DIR = $(SRC_DIR)/inc

# Source files
SRCS    := $(wildcard $(SRC_DIR)/*.c) $(wildcard $(BSP_DIR)/*.c)
ASRCS   := $(wildcard $(SRC_DIR)/*.s) $(wildcard $(BSP_DIR)/*.s)
OPT_SRCS := $(wildcard $(SCRIPTS_DIR)/*.opt)

# Compiler tools
CC       = $(TOOLCHAIN)/sdcc
LD       = $(TOOLCHAIN)/sdld
AS       = $(TOOLCHAIN)/sdasstm8
OBJCOPY  = $(TOOLCHAIN)/sdobjcopy

# Compiler flags
ASFLAGS  = -plosgff
CFLAGS   = -m$(ARCH) -p$(MCU) --std-sdcc11
CFLAGS  += -DF_CPU=$(F_CPU)UL -I$(SRC_INC_DIR) -I$(BSP_INC_DIR)
CFLAGS  += --stack-auto --noinduction --use-non-free
## Disable lospre (workaround for bug 2673)
#CFLAGS  += --nolospre
LDFLAGS  = -m$(ARCH) -l$(ARCH) --out-fmt-ihx

OPTION_BOOT := 0x480D
RAM_BOOT    := 0x0253
OPTFLAGS = -Wl-bOPTION=0x4800 -Wl-bOPTION_BOOT=$(OPTION_BOOT)
B2FLAGS  = -Wl-bRAM_BOOT=$(RAM_BOOT)

# Conditionally add ENABLE_OPTION_BOOTLOADER macro
ifneq ($(ENABLE_OPTION_BOOTLOADER),0)
    CFLAGS += -DENABLE_OPTION_BOOTLOADER
    BOOT_SUFFIX = _boot
else
    BOOT_SUFFIX =
endif


# Object files
OBJS     = $(patsubst %.c,$(BUILD_DIR)/%.rel,$(notdir $(SRCS))) \
           $(patsubst %.s,$(BUILD_DIR)/%.rel,$(notdir $(ASRCS)))
OPT_OBJS = $(patsubst %.opt,$(BUILD_DIR)/%.rel,$(notdir $(OPT_SRCS)))

# Source file search paths
vpath %.c $(sort $(dir $(SRCS)))
vpath %.s $(sort $(dir $(ASRCS)))
vpath %.opt $(sort $(dir $(OPT_SRCS)))

# Default target: build main application and option bytes
all: $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin $(BUILD_DIR)/option.bin size

# Compile C files
$(BUILD_DIR)/%.rel: %.c | $(BUILD_DIR)
	@mkdir -p $(dir $@)
	$(CC) -c $(CFLAGS) $< -o $@

# Compile assembly files
$(BUILD_DIR)/%.rel: %.s | $(BUILD_DIR)
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) $<
	@mv $(SRC_DIR)$*.lst $(SRC_DIR)$*.rel $(SRC_DIR)$*.sym $(BUILD_DIR)/ 2>/dev/null || true

# Compile option byte files
$(BUILD_DIR)/%.rel: %.opt | $(BUILD_DIR)
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) $<
	$(eval SRC_DIR := $(dir $<))
	@mv $(SRC_DIR)$*.lst $(SRC_DIR)$*.rel $(SRC_DIR)$*.sym $(BUILD_DIR)/ 2>/dev/null || true

# Link main application
$(BUILD_DIR)/$(TARGET).hex: $(OBJS)
	$(CC) $(LDFLAGS) $(OBJS) -o $@

$(BUILD_DIR)/$(TARGET).bin: $(BUILD_DIR)/$(TARGET).hex
	$(OBJCOPY) -I ihex --output-target=binary $< $@

# Adjust vector table for bootloader mode (swap reset and trap vectors)
ifeq ($(ENABLE_OPTION_BOOTLOADER),1)
$(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin: $(BUILD_DIR)/$(TARGET).bin
	@echo "Adjusting vector table for bootloader mode..."
	@# Extract reset vector (bytes 2-4)
	@dd if=$< of=$(BUILD_DIR)/reset.bin bs=1 skip=1 count=3 2>/dev/null
	@# Extract trap vector (bytes 5-8)
	@dd if=$< of=$(BUILD_DIR)/trap.bin bs=1 skip=4 count=4 2>/dev/null
	@# Swap vectors and change first byte of trap vector to 0xAC (JPF)
	@# 1. Write trap vector to output (becomes new reset vector)
	@cat $(BUILD_DIR)/trap.bin > $@
	@# 2. Write reset vector to output (load in wrap vector)
	@printf "\xAC" >> $@
	@cat $(BUILD_DIR)/reset.bin >> $@
	@# 3. Append the rest of the file
	@dd if=$< bs=1 skip=8 >> $@ 2>/dev/null
	@# Clean up temporary files
	@echo "    Reset vector moved to trap position with JPF (0xAC) instruction"
	@echo "    Created bootloader-ready binary: $@"
endif

# Link option bytes separately at address 0x4800
$(BUILD_DIR)/option.hex: $(OPT_OBJS)
	$(CC) $(LDFLAGS) $(OPTFLAGS) $(OPT_OBJS) -o $@

$(BUILD_DIR)/option.bin: $(BUILD_DIR)/option.hex
	$(OBJCOPY) -I ihex --output-target=binary $< $@

boot2: $(SCRIPTS_DIR)/boot2.s | $(BUILD_DIR)
	$(AS) $(ASFLAGS) $<
	@mv $(SCRIPTS_DIR)/boot2.lst $(SCRIPTS_DIR)/boot2.rel $(SCRIPTS_DIR)/boot2.sym $(BUILD_DIR)/ 2>/dev/null || true
	$(CC) $(LDFLAGS) $(B2FLAGS) $(BUILD_DIR)/boot2.rel -o $(BUILD_DIR)/boot2.hex
	$(OBJCOPY) -I ihex --output-target=binary $(BUILD_DIR)/boot2.hex $(SCRIPTS_DIR)/boot2.bin
	@# Check boot2 load address
	@B2SIZE=$$(wc -c < $(SCRIPTS_DIR)/boot2.bin); \
	SIZE1K=$$(($$B2SIZE+$(RAM_BOOT)+(0x4840-$(OPTION_BOOT)-3))); \
	if [ $$SIZE1K -ne 1024 ]; then \
		echo ""; \
		echo "!!! boot2 ram address error!!!"; \
		NEW_RAM_BOOT=$$((1024-$$SIZE1K+$(RAM_BOOT))); \
		echo "    RAM_BOOT: $(RAM_BOOT) -> 0x$$(printf "%X" $$NEW_RAM_BOOT)"; \
	fi

# Show sizes of generated binaries
size: $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin $(BUILD_DIR)/option.bin
	@echo "=== Main application size ==="
	@wc -c $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin
	@echo ""
	@echo "=== Option bytes size ==="
	@wc -c $(BUILD_DIR)/option.bin

# Create build directory
$(BUILD_DIR):
	mkdir -p $@

# Clean build directory
clean:
	rm -fR $(BUILD_DIR)

# Flash main application and option bytes via ST-Link
flash: $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin $(BUILD_DIR)/option.bin
	@echo "Flashing main application..."
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -w $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin
	@echo ""
	@echo "Flashing option bytes..."
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -s opt -w $(BUILD_DIR)/option.bin

# Flash only option bytes
flash-opt: $(BUILD_DIR)/option.bin
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -s opt -w $(BUILD_DIR)/option.bin

# Flash only main application
flash-app: $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -w $(BUILD_DIR)/$(TARGET)$(BOOT_SUFFIX).bin

# Show help information
help:
	@echo "Available targets:"
	@echo "  all        - Build main application and option bytes (default)"
	@echo "  clean      - Remove build directory"
	@echo "  flash      - Flash main application and option bytes"
	@echo "  flash-app  - Flash only main application"
	@echo "  flash-opt  - Flash only option bytes"
	@echo "  boot2      - Build boot2 application"
	@echo "  size       - Show sizes of generated binaries"
	@echo "  help       - Show this help"

.PHONY: clean all flash flash-opt flash-app size boot2 help
