/* Experimental RAM-kernel SDHCI gate; NOT deployed and NOT a flash image.
 * a0=sdhci_host*, a1=mmc_command*. Verified stock offsets: data=44,
 * data.flags=20, command.error=32. No MMIO and no external calls here.
 * Denial reuses the stock inhibit-timeout tasklet path after saving its
 * exact stack frame. CMD6 errors use MIPS EBADMSG=77; other denials EROFS=30.
 */
.set noreorder
.set noat
.text
.globl storage_guard
storage_guard:
    /* Exact module resource -> __ioremap -> host.ioaddr proof in evidence.
     * Only read the host RAM field; never dereference the MMIO address. */
    lw $t0,0($a1)
    addiu $t1,$zero,52
    beq $t0,$t1,sdio_host
    nop
    addiu $t1,$zero,53
    bne $t0,$t1,golden_policy
    nop
sdio_host:
    lw $t0,16($a0)
    lui $t1,0xb346
    bne $t0,$t1,golden_policy
    nop
    lw $t0,0($a1)
    addiu $t1,$zero,52
    bne $t0,$t1,sdio_extended
    nop
    /* CMD52 has no data phase and reserved bits 26/8 must be zero. */
    lw $t0,44($a1)
    bne $t0,$zero,deny_write
    nop
    lw $t0,4($a1)
    lui $t1,0x0400
    ori $t1,$t1,0x0100
    and $t0,$t0,$t1
    bne $t0,$zero,deny_write
    nop
    b allow
    nop
sdio_extended:
    /* CMD53 needs exactly one direction, matching argument bit31. */
    lw $t0,44($a1)
    beq $t0,$zero,deny_write
    nop
    lw $t0,20($t0)
    lw $t1,4($a1)
    srl $t1,$t1,31
    bne $t1,$zero,sdio_write
    nop
    addiu $t1,$zero,0x0200
    bne $t0,$t1,deny_write
    nop
    b allow
    nop
sdio_write:
    addiu $t1,$zero,0x0100
    bne $t0,$t1,deny_write
    nop
    b allow
    nop
golden_policy:
    lw $t0,44($a1)
    beq $t0,$zero,opcode
    nop
    lw $t1,20($t0)
    andi $t2,$t1,0x0100
    bne $t2,$zero,deny_write
    nop
    andi $t1,$t1,0x0200
    beq $t1,$zero,deny_write
    nop
opcode:
    lw $t0,0($a1)
    sltiu $t1,$t0,32
    beq $t1,$zero,deny_write
    nop
    addiu $t1,$zero,6
    beq $t0,$t1,switch_command
    nop
    addiu $t1,$zero,23
    beq $t0,$t1,block_count
    nop
    lui $t1,0x00a7
    ori $t1,$t1,0x37af
    srlv $t1,$t1,$t0
    andi $t1,$t1,1
    beq $t1,$zero,deny_write
    nop
allow:
    /* Relocated original first two instructions at 0x8035c450. */
    addiu $sp,$sp,-104
    sw $s6,88($sp)
    j 0x8035c458
    nop
block_count:
    lw $t1,4($a1)
    srl $t1,$t1,16
    bne $t1,$zero,deny_write
    nop
    b allow
    nop
switch_command:
    lw $t2,44($a1)
    bne $t2,$zero,deny_switch
    nop
    lw $t1,4($a1)
    srl $t2,$t1,26
    bne $t2,$zero,deny_switch
    nop
    srl $t2,$t1,24
    andi $t2,$t2,3
    addiu $t3,$zero,3
    bne $t2,$t3,deny_switch
    nop
    andi $t2,$t1,0xff
    sltiu $t2,$t2,2
    beq $t2,$zero,deny_switch
    nop
    srl $t2,$t1,16
    andi $t2,$t2,0xff
    addiu $t3,$zero,183
    beq $t2,$t3,bus_width
    nop
    addiu $t3,$zero,185
    bne $t2,$t3,deny_switch
    nop
    srl $t2,$t1,8
    andi $t2,$t2,0xff
    sltiu $t2,$t2,4
    beq $t2,$zero,deny_switch
    nop
    b allow
    nop
bus_width:
    srl $t2,$t1,8
    andi $t2,$t2,0xff
    sltiu $t3,$t2,3
    bne $t3,$zero,allow
    nop
    addiu $t3,$zero,5
    beq $t2,$t3,allow
    nop
    addiu $t3,$zero,6
    beq $t2,$t3,allow
    nop
deny_switch:
    addiu $t0,$zero,-77
    b denied
    nop
deny_write:
    addiu $t0,$zero,-30
denied:
    sw $t0,32($a1)
    /* Exact stock prologue through the saved registers, without MMIO. */
    addiu $sp,$sp,-104
    sw $s6,88($sp)
    sw $s1,68($sp)
    sw $ra,100($sp)
    sw $s8,96($sp)
    sw $s7,92($sp)
    sw $s5,84($sp)
    sw $s4,80($sp)
    sw $s3,76($sp)
    sw $s2,72($sp)
    sw $s0,64($sp)
    move $s6,$a0
    move $s1,$a1
    j 0x8035c518
    nop
