# Toolchain and programmer paths
TOOLCHAIN ?= /opt/Developer/sdcc/bin
ISPTOOL ?= /opt/Developer/stm8flash

# MCU configuration
MCU  = stm8s103f3
ARCH = stm8

# Compilation settings
F_CPU   ?= 2000000
TARGET  ?= $(lastword $(subst /, ,$(CURDIR)))

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
OPTFLAGS = -Wl-bOPTION=0x4800 -Wl-bOPTION_BOOT=0x481C

# Object files
OBJS     = $(patsubst %.c,$(BUILD_DIR)/%.rel,$(notdir $(SRCS))) \
           $(patsubst %.s,$(BUILD_DIR)/%.rel,$(notdir $(ASRCS)))
OPT_OBJS = $(patsubst %.opt,$(BUILD_DIR)/%.rel,$(notdir $(OPT_SRCS)))

# Source file search paths
vpath %.c $(sort $(dir $(SRCS)))
vpath %.s $(sort $(dir $(ASRCS)))
vpath %.opt $(sort $(dir $(OPT_SRCS)))

# Default target: build main application and option bytes
all: $(BUILD_DIR)/$(TARGET).bin $(BUILD_DIR)/option.bin size

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

# Link option bytes separately at address 0x4800
$(BUILD_DIR)/option.hex: $(OPT_OBJS)
	$(CC) $(LDFLAGS) $(OPTFLAGS) $(OPT_OBJS) -o $@ || true

$(BUILD_DIR)/option.bin: $(BUILD_DIR)/option.hex
	$(OBJCOPY) -I ihex --output-target=binary $< $@

# Show sizes of generated binaries
size: $(BUILD_DIR)/$(TARGET).bin $(BUILD_DIR)/option.bin
	@echo "=== Main application size ==="
	@wc -c $(BUILD_DIR)/$(TARGET).bin
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
flash: $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/option.hex
	@echo "Flashing main application..."
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -w $(BUILD_DIR)/$(TARGET).hex
	@echo ""
	@echo "Flashing option bytes..."
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -s opt -w $(BUILD_DIR)/option.hex

# Flash only option bytes
flash-opt: $(BUILD_DIR)/option.hex
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -s opt -w $(BUILD_DIR)/option.hex

# Flash only main application
flash-app: $(BUILD_DIR)/$(TARGET).hex
	$(ISPTOOL) -c stlinkv2 -p $(MCU) -w $(BUILD_DIR)/$(TARGET).hex

# Build only option bytes
option: $(BUILD_DIR)/option.bin

# Show help information
help:
	@echo "Available targets:"
	@echo "  all        - Build main application and option bytes (default)"
	@echo "  clean      - Remove build directory"
	@echo "  flash      - Flash main application and option bytes via ST-Link"
	@echo "  flash-app  - Flash only main application"
	@echo "  flash-opt  - Flash only option bytes"
	@echo "  size       - Show sizes of generated binaries"
	@echo "  option     - Build only option bytes"
	@echo "  help       - Show this help"

.PHONY: clean all flash flash-opt flash-app size option help
