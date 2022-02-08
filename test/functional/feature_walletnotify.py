# Copyright (c)  The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test -walletnotify."""

import os
from decimal import getcontext

from test_framework.test_framework import BitcoinTestFramework

NODE_DIR = "node0"
FILE_NAME = "test.txt"


class WalletNotifyTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        getcontext().prec = 8  # Satoshi precision for Decimal
        self.disable_syscall_sandbox = True
        self.requires_wallet = True

    def skip_test_if_missing_module(self):
        self.skip_if_no_wallet()

    def run_test(self):
        tmpdir_file = os.path.join(self.options.tmpdir, NODE_DIR, FILE_NAME)
        assert os.path.exists(self.options.tmpdir)
        assert not os.path.exists(tmpdir_file)

        self.log.info("Test -walletnotify command is run when wallet receives bitcoin")
        self.restart_node(0, extra_args=[f"-walletnotify=echo 's:%s b:%b w:%w h:%h' >> {NODE_DIR}/{FILE_NAME}"])
        node = self.nodes[0]
        node.createwallet("w0")
        w = node.get_wallet_rpc("w0")

        blockhash = self.generatetoaddress(node, 1, w.getnewaddress(), sync_fun=lambda: self.sync_all())[0]
        block = node.getblock(blockhash)
        tx = block['tx'][0]
        self.wait_until(lambda: os.path.exists(tmpdir_file))

        self.log.info("Test -walletnotify is executed when a wallet transaction changes")
        with open(tmpdir_file, "r", encoding="utf8") as f:
            file_content = f.read()
            expected = f"s:{tx} b:{blockhash} w:w0 h:{block['height']}"
            assert (expected in file_content)


if __name__ == '__main__':
    WalletNotifyTest().main()
